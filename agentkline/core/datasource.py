"""
AgentKline - 数据源管理
管理轮询数据源（异步任务）
"""
import asyncio
import json
import threading
import logging
from typing import Optional
from datetime import datetime, timedelta

logger = logging.getLogger("agentkline.datasource")


class DataSourceManager:
    """数据源管理器（轮询）"""

    def __init__(self, state, script_engine, service=None, hub=None):
        self.state = state
        self.script_engine = script_engine
        self.service = service  # 指标重算委托（v0.4 实例模型）
        # v0.7.2：可选的行情请求合并层；None 时保持旧路径（测试/一次性实例）
        self.hub = hub
        self.tasks: dict[str, 'threading.Thread'] = {}  # key -> poll thread（v0.4.3：asyncio task+executor 链两度不可解释挂起，换线程模型，watchlist Timer 先例稳定）
        self._stop_flags: dict[str, bool] = {}
        self._wake: dict[str, 'threading.Event'] = {}  # v0.4.3 bug5 根治：可中断 sleep（view 上报/切槽唤醒长睡 loop）
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

    # ---- v0.7.2 行情合并键/热度 ----
    @staticmethod
    def _hub_key(script: str, params: dict, timeframe: str, until=None) -> str:
        """同一源+同一组参数+同一周期=同一 key；until 只用于回补，单独区分。"""
        payload = json.dumps(params or {}, sort_keys=True, ensure_ascii=False,
                             default=str, separators=(",", ":"))
        suffix = f"|until={until}" if until is not None else ""
        return f"{script}|{timeframe}|{payload}{suffix}"

    def _is_hot(self, board_id: str, timeframe: str) -> bool:
        """当前图表/模拟盘所在槽=热；其余槽可以缓存更久。"""
        view = getattr(self.service, "current_view", None) or {}
        if view.get("board_id") == board_id and view.get("timeframe") == timeframe:
            return True
        board = getattr(self.state, "get_board", lambda _x: None)(board_id)
        if board is not None and getattr(board, "current_timeframe", None) == timeframe:
            return True
        paper = getattr(self.service, "paper", None) if self.service else None
        if paper is not None:
            try:
                if paper.is_active_timeframe(board_id, timeframe):
                    return True
            except Exception:
                pass
        return False

    def _fetch(self, script: str, params: dict, timeframe: str, *,
               board_id: str = None, until=None, force: bool = False) -> dict:
        """统一取数入口：有 hub 则 single-flight/TTL/预算；否则旧直连。"""
        if self.hub is None:
            return self.script_engine.run_script(script, params, until=until)
        key = self._hub_key(script, params, timeframe, until=until)
        if force:
            self.hub.invalidate(key=key)
        ttl = 0.0 if until is not None else (
            self.hub.ttl_active_s if (board_id and self._is_hot(board_id, timeframe))
            else self.hub.ttl_idle_s)
        return self.hub.fetch(key, script,
                              lambda: self.script_engine.run_script(script, params, until=until),
                              ttl_s=ttl)

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
            "poll_s": poll_s or 5,   # v0.4.4 bug10：缺失兜底 5，防 None 语义漂移
        }
        self.status.setdefault(key, {})

    def start_polling(self):
        """启动轮询调度（在 lifespan 中调用）"""
        logger.info("DataSource polling scheduler started")

    def start(self, board_id: str, timeframe: str, script: str, params: dict, poll_s: int):
        """启动一个轮询数据源；script 为 id（kind/name）；配置与运行态分家"""
        poll_s = poll_s or 5   # v0.4.4 bug10 choke 点兜底（调用方不传 poll_s 曾致线程不启=价格永冻）
        key = self._key(board_id, timeframe)

        # 先停止旧的
        if key in self.tasks:
            self._stop_flags[key] = True
            self.tasks.pop(key, None)

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

        # 创建轮询线程（daemon；stop 族用 flag 协作退出）
        self._stop_flags[key] = False
        th = threading.Thread(target=self._poll_thread, args=(key,), daemon=True,
                              name=f"ak-poll-{key}")
        self.tasks[key] = th
        th.start()
        logger.info(f"DataSource started: {key} (poll_s={poll_s}s)")

    def stop_sync(self, board_id: str, timeframe: str):
        """同步停槽（set_kline_source 等同步路径用）：取消任务+清配置"""
        key = self._key(board_id, timeframe)
        if self.tasks.pop(key, None):
            self._stop_flags[key] = True
        self.configs.pop(key, None)

    async def stop(self, board_id: str, timeframe: str):
        """停止一个轮询数据源"""
        key = self._key(board_id, timeframe)
        if key in self.tasks:
            self._stop_flags[key] = True
            del self.tasks[key]
        if key in self.configs:
            del self.configs[key]
        if key in self.error_counts:
            del self.error_counts[key]
        logger.info(f"DataSource stopped: {key}")

    def stop_all(self):
        """停止所有轮询"""
        for key in list(self.tasks.keys()):
            self._stop_flags[key] = True
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
        """合并 K 线：保留更早历史 + 新窗口；按 timestamp 去重（后者覆盖前者）。

        v0.7.2：上游重复 bar 不再进入内存时间轴，避免 paper 重复决策；
        排序保证 bisect/新 bar 判定稳定。"""
        if not new:
            return sorted(existing or [], key=lambda b: int(b["timestamp"]))
        by_ts = {}
        for b in (existing or []):
            try:
                by_ts[int(b["timestamp"])] = b
            except (KeyError, TypeError, ValueError):
                continue
        for b in new:
            try:
                by_ts[int(b["timestamp"])] = b
            except (KeyError, TypeError, ValueError):
                continue
        return [by_ts[k] for k in sorted(by_ts)]

    # ---- v0.4.1 性能①：可见性分级轮询 ----
    @staticmethod
    def _decay_s(timeframe: str) -> int:
        """非可见槽降频：<=1h→60s；<=4h→120s；>=1d→300s"""
        tf = (timeframe or "").lower()
        try:
            v = int(tf[:-1]); u = tf[-1]
        except (ValueError, IndexError):
            return 60
        mins = v * {"m": 1, "h": 60, "d": 1440, "w": 10080}.get(u, 60)
        return 60 if mins <= 60 else (120 if mins <= 240 else 300)

    def effective_poll_s(self, config: dict) -> int:
        base = config.get("poll_s") or 5
        view = getattr(self.service, "current_view", None) or {}
        if view.get("board_id") == config.get("board_id") and \
                view.get("timeframe") == config.get("timeframe"):
            return base
        # v0.4.4 bug11：无浏览器上报（headless/重启后未开页）时 current_view 空 →
        # 原连当前槽也降频 300s = REST/MCP 消费方见"价格永冻"。空 view = 各板当前槽免降频。
        if not view:
            board = getattr(self.service, "state", None)
            b = board.get_board(config.get("board_id")) if board else None
            if b and getattr(b, "current_timeframe", None) == config.get("timeframe"):
                return base
        # v0.7.0：模拟盘所在槽即使不是当前图表，也按基础频率轮询；
        # 否则 15m 模拟盘会被 1h 可见槽的降频规则拖到 60s，面板/bar 处理都变慢。
        paper = getattr(self.service, "paper", None)
        if paper is not None:
            try:
                if paper.is_active_timeframe(config.get("board_id"), config.get("timeframe")):
                    return base
            except Exception:
                pass
        return self._decay_s(config.get("timeframe"))

    def poke(self, board_id: str, timeframe: str):
        """切即补拉/视图命中：标记 force + 唤醒长睡 loop（Event.set），立即补拉"""
        key = self._key(board_id, timeframe)
        st = self.status.setdefault(key, {})
        st["force"] = True
        ev = self._wake.setdefault(key, threading.Event())
        ev.set()

    def _poll_thread(self, key: str):
        """轮询线程（v0.4.3 线程模型）：周期 sleep→同步 run_script→合并写 state→
        广播走 service 同步面（_sync_notify 跨线程投递契约）。整体 try 防静默死。"""
        import time as _t
        board_id, timeframe = key.rsplit(":", 1)  # _key 分隔符=冒号（board 名不含冒号）
        try:
            while not self._stop_flags.get(key, False):
                config = self.configs.get(key)
                if not config or config.get("mode") != "poll":
                    break
                interval = self.effective_poll_s(config)
                script = config["script"]
                params = config["params"]
                st0 = self.status.setdefault(key, {})
                if not st0.pop("force", False):
                    ev = self._wake.setdefault(key, threading.Event())
                    ev.wait(interval)   # 可中断：poke/report_view set 即醒（长睡陷阱根治）
                    ev.clear()
                if key not in self.configs:
                    break
                _c0 = _t.time()
                try:
                    result = self._fetch(script, params, timeframe, board_id=board_id)
                except Exception as e:
                    result = {"error": f"POLL_EXCEPTION: {e}"}
                _fetch_s = _t.time() - _c0
                if _fetch_s > 8:
                    logger.warning(f"poll fetch 慢: {key} {_fetch_s:.1f}s（网络/线程池拥塞信号）")

                if result.get("error"):
                    self.error_counts[key] = self.error_counts.get(key, 0) + 1
                    logger.warning(f"DataSource error ({self.error_counts[key]}): {key}: {result['error']}")
                    st = self.status.setdefault(key, {})
                    st["last_error"] = result["error"]
                    st["last_fetch"] = datetime.now().isoformat()
                    paper = getattr(self.service, "paper", None) if self.service else None
                    if paper is not None:
                        try:
                            paper.on_source_error(board_id, timeframe, result["error"])
                        except Exception:
                            logger.debug("paper stale 调度失败", exc_info=True)
                    if self.error_counts[key] >= 3 and self.ws_manager:
                        self.service.notify({"type": "datasource_error",
                                             "board_id": board_id, "timeframe": timeframe,
                                             "error": result["error"], "retry_after": interval})
                    continue

                self.error_counts[key] = 0
                st = self.status.setdefault(key, {})
                st["last_error"] = None
                st["eff_poll_s"] = self.effective_poll_s(config)
                st["last_fetch"] = datetime.now().isoformat()
                st["next_due"] = (datetime.now() + timedelta(seconds=interval)).isoformat()
                _prev = st.get("_prev_done")
                st["_prev_done"] = _t.time()
                if _prev and (_t.time() - _prev) > 3 * max(interval, 5) + 15:
                    logger.warning(f"poll gap 异常: {key} 周期空窗 {_t.time() - _prev:.0f}s（eff={interval}）")

                data = result.get("data", [])
                if data:
                    existing = self.state.get_ohlcv(board_id, timeframe)
                    merged = self._merge_ohlcv(existing, data)
                    self.state.set_ohlcv(board_id, timeframe, merged)
                    if self.service:
                        # v0.7.0：只唤醒 paper worker，不在这里跑策略/撮合
                        paper = getattr(self.service, "paper", None)
                        if paper is not None:
                            try:
                                paper.on_bars(board_id, timeframe, existing, merged)
                            except Exception:
                                logger.exception("paper on_bars 失败: %s:%s",
                                                 board_id, timeframe)
                        self.service.recompute_indicators(board_id, timeframe)
                        self.service.bc_ohlcv_delta(board_id, timeframe, existing, merged)
        except Exception as e:
            logger.error(f"poll thread 死: {key}: {e!r}")
        finally:
            logger.info(f"poll thread exit: {key}")

    async def _refresh_indicators(self, board_id: str, timeframe: str):
        """重算 recipe 指标实例：委托 service.recompute_indicators（含尾窗+广播 wire）"""
        if self.service:
            self.service.recompute_indicators(board_id, timeframe)
