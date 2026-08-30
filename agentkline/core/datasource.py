"""
AgentKline - 数据源管理
管理轮询数据源（异步任务）
"""
import asyncio
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger("agentkline.datasource")


class DataSourceManager:
    """数据源管理器（轮询）"""

    def __init__(self, state, script_engine):
        self.state = state
        self.script_engine = script_engine
        self.tasks: dict[str, asyncio.Task] = {}  # key -> task
        self.configs: dict[str, dict] = {}        # key -> config
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

    def set_config(self, board_id: str, timeframe: str, path: str, params: dict, interval: int = None):
        """记录数据源配置（一次性或轮询都记录，供历史回溯使用）"""
        key = self._key(board_id, timeframe)
        self.configs[key] = {
            "board_id": board_id,
            "timeframe": timeframe,
            "path": path,
            "params": params,
            "poll_interval": interval,
        }

    def start_polling(self):
        """启动轮询调度（在 lifespan 中调用）"""
        logger.info("DataSource polling scheduler started")

    def start(self, board_id: str, timeframe: str, path: str, params: dict, interval: int):
        """启动一个轮询数据源"""
        key = self._key(board_id, timeframe)

        # 先停止旧的
        if key in self.tasks:
            self.tasks[key].cancel()

        self.configs[key] = {
            "board_id": board_id,
            "timeframe": timeframe,
            "path": path,
            "params": params,
            "poll_interval": interval,
            "started_at": datetime.now().isoformat()
        }
        self.error_counts[key] = 0

        # 创建异步任务
        task = asyncio.create_task(self._poll_loop(key))
        self.tasks[key] = task
        logger.info(f"DataSource started: {key} (interval={interval}s)")

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
        """获取数据源配置"""
        key = self._key(board_id, timeframe)
        return self.configs.get(key)

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
        """轮询循环"""
        config = self.configs.get(key)
        if not config:
            return

        interval = config["poll_interval"]
        board_id = config["board_id"]
        timeframe = config["timeframe"]
        path = config["path"]
        params = config["params"]

        while True:
            try:
                await asyncio.sleep(interval)

                # 检查是否还在
                if key not in self.configs:
                    break

                # 执行脚本
                result = await asyncio.get_event_loop().run_in_executor(
                    None, self.script_engine.run_script, path, params
                )

                if result.get("error"):
                    self.error_counts[key] = self.error_counts.get(key, 0) + 1
                    logger.warning(f"DataSource error ({self.error_counts[key]}): {key}: {result['error']}")

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

                # 成功，重置错误计数
                self.error_counts[key] = 0

                # 更新K线（合并：保留更早历史 + 更新近期窗口）
                data = result.get("data", [])
                if data:
                    existing = self.state.get_ohlcv(board_id, timeframe)
                    merged = self._merge_ohlcv(existing, data)
                    self.state.set_ohlcv(board_id, timeframe, merged)

                    # 重算动态指标
                    await self._refresh_indicators(board_id, timeframe)

                    # 推送更新
                    if self.ws_manager:
                        await self.ws_manager.broadcast({
                            "type": "ohlcv_update",
                            "board_id": board_id,
                            "timeframe": timeframe,
                            "data": merged,
                            "markers": []
                        })

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"DataSource poll error: {key}: {e}")
                await asyncio.sleep(1)

    async def _refresh_indicators(self, board_id: str, timeframe: str):
        """重算动态指标"""
        ohlcv = self.state.get_ohlcv(board_id, timeframe)
        if not ohlcv:
            return

        dynamic_indicators = self.state.get_dynamic_indicators(board_id, timeframe)
        for ind in dynamic_indicators:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self.script_engine.run_indicator_script,
                ind["path"], ohlcv, ind.get("params", {})
            )
            if not result.get("error") and result.get("values"):
                self.state.set_indicator(board_id, timeframe, ind["name"], values=result["values"])
                if self.ws_manager:
                    await self.ws_manager.broadcast({
                        "type": "indicator_refresh",
                        "board_id": board_id,
                        "timeframe": timeframe,
                        "name": ind["name"],
                        "values": result["values"],
                        "subplot": ind.get("subplot")
                    })
