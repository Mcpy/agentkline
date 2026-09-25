"""
AgentKline - 数据源管理
管理轮询数据源（异步任务）
"""
import asyncio
import logging
from typing import Optional
from datetime import datetime, timedelta

logger = logging.getLogger("agentkline.datasource")


class DataSourceManager:
    """数据源管理器（轮询）"""

    def __init__(self, state, script_engine, service=None):
        self.state = state
        self.script_engine = script_engine
        self.service = service  # 指标重算委托（v0.4 实例模型）
        self.tasks: dict[str, asyncio.Task] = {}  # key -> task
        self.configs: dict[str, dict] = {}        # key -> 纯配置 {script,params,mode,poll_s}
        self.status: dict[str, dict] = {}         # key -> 运行态 {last_error,last_fetch,next_due,started_at}
        self.error_counts: dict[str, int] = {}    # key -> 连续错误次数
        self._ws_manager = None  # 延迟注入

    @property
    def ws_manager(self):
        return self._ws_manager

    @ws_manager.setter
    def ws_manager(self, val):
        self._ws_manager = val

    def _key(self, board_id: str, timeframe: str) -> str:
        return f"{board_id}:{timeframe}"

    def set_config(self, board_id: str, timeframe: str, script: str, params: dict, poll_s: int = None):
        """记录槽配置（纯配置，永远 JSON 可序列化）；script 为 id（kind/name）。
        配置={script,params,mode,poll_s}；运行态(last_error/last_fetch/next_due)挂 status，分家。"""
        key = self._key(board_id, timeframe)
        self.configs[key] = {
            "board_id": board_id,
            "timeframe": timeframe,
            "script": script,
            "params": params,
            "mode": "poll" if (poll_s and poll_s > 0) else "once",
            "poll_s": poll_s if (poll_s and poll_s > 0) else None,
        }
        self.status.setdefault(key, {})

    def start_polling(self):
        """启动轮询调度（在 lifespan 中调用）"""
        logger.info("DataSource polling scheduler started")

    def start(self, board_id: str, timeframe: str, script: str, params: dict, poll_s: int):
        """启动一个轮询数据源；script 为 id（kind/name）；配置与运行态分家"""
        key = self._key(board_id, timeframe)

        # 先停止旧的
        if key in self.tasks:
            self.tasks[key].cancel()

        self.configs[key] = {
            "board_id": board_id,
            "timeframe": timeframe,
            "script": script,
            "params": params,
            "mode": "poll",
            "poll_s": poll_s,
        }
        self.status[key] = {"started_at": datetime.now().isoformat(),
                            "last_error": None, "last_fetch": None, "next_due": None}
        self.error_counts[key] = 0

        # 创建异步任务
        task = asyncio.create_task(self._poll_loop(key))
        self.tasks[key] = task
        logger.info(f"DataSource started: {key} (poll_s={poll_s}s)")

    def stop_sync(self, board_id: str, timeframe: str):
        """同步停槽（set_kline_source 等同步路径用）：取消任务+清配置"""
        key = self._key(board_id, timeframe)
        task = self.tasks.pop(key, None)
        if task:
            task.cancel()
        self.configs.pop(key, None)

    async def stop(self, board_id: str, timeframe: str):
        """停止一个轮询数据源"""
        key = self._key(board_id, timeframe)
        if key in self.tasks:
            self.tasks[key].cancel()
            del self.tasks[key]
        if key in self.configs:
            del self.configs[key]
        if key in self.error_counts:
            del self.error_counts[key]
        logger.info(f"DataSource stopped: {key}")

    def stop_all(self):
        """停止所有轮询"""
        for key in list(self.tasks.keys()):
            self.tasks[key].cancel()
        self.tasks.clear()
        self.configs.clear()
        logger.info("All datasources stopped")

    def get(self, board_id: str, timeframe: str) -> Optional[dict]:
        """获取槽配置 + 运行态（配置/状态分家后的合并视图，仅供读取展示）"""
        key = self._key(board_id, timeframe)
        config = self.configs.get(key)
        if not config:
            return None
        return {**config, "status": self.status.get(key, {})}

    @staticmethod
    def _merge_ohlcv(existing: list, new: list) -> list:
        """合并K线：保留比新窗口更早的历史 + 新窗口（更新/追加近期）"""
        if not existing:
            return sorted(new, key=lambda b: b["timestamp"])
        new_sorted = sorted(new, key=lambda b: b["timestamp"])
        new_earliest = new_sorted[0]["timestamp"]
        older = [b for b in existing if b["timestamp"] < new_earliest]
        return older + new_sorted

    async def _poll_loop(self, key: str):
        """轮询循环；每轮动态读配置（poll_s 改即时生效，不碰数据不重启）"""
        config = self.configs.get(key)
        if not config:
            return

        board_id = config["board_id"]
        timeframe = config["timeframe"]

        while True:
            config = self.configs.get(key)
            if not config or config.get("mode") != "poll":
                break
            interval = config.get("poll_s") or 5
            script = config["script"]
            params = config["params"]
            try:
                await asyncio.sleep(interval)

                # 检查是否还在
                if key not in self.configs:
                    break

                # 执行脚本
                result = await asyncio.get_event_loop().run_in_executor(
                    None, self.script_engine.run_script, script, params
                )

                if result.get("error"):
                    self.error_counts[key] = self.error_counts.get(key, 0) + 1
                    logger.warning(f"DataSource error ({self.error_counts[key]}): {key}: {result['error']}")
                    st = self.status.setdefault(key, {})
                    st["last_error"] = result["error"]
                    st["last_fetch"] = datetime.now().isoformat()

                    # 3次失败后通知
                    if self.error_counts[key] >= 3 and self.ws_manager:
                        await self.ws_manager.broadcast({
                            "type": "datasource_error",
                            "board_id": board_id,
                            "timeframe": timeframe,
                            "error": result["error"],
                            "retry_after": interval
                        })
                    continue

                # 成功，重置错误计数 + 运行态
                self.error_counts[key] = 0
                st = self.status.setdefault(key, {})
                st["last_error"] = None
                st["last_fetch"] = datetime.now().isoformat()
                st["next_due"] = (datetime.now() + timedelta(seconds=interval)).isoformat()

                # 更新K线（合并：保留更早历史 + 更新近期窗口）
                data = result.get("data", [])
                if data:
                    existing = self.state.get_ohlcv(board_id, timeframe)
                    merged = self._merge_ohlcv(existing, data)
                    self.state.set_ohlcv(board_id, timeframe, merged)

                    # 重算动态指标
                    await self._refresh_indicators(board_id, timeframe)

                    # 推送更新（R8 差量化：只推前插/追加/尾部更新）
                    if self.service:
                        self.service.bc_ohlcv_delta(board_id, timeframe, existing, merged)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"DataSource poll error: {key}: {e}")
                await asyncio.sleep(1)

    async def _refresh_indicators(self, board_id: str, timeframe: str):
        """重算 recipe 指标实例：委托 service.recompute_indicators（含尾窗+广播 wire）"""
        if self.service:
            self.service.recompute_indicators(board_id, timeframe)
