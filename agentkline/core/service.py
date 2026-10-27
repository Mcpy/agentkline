"""
AgentKline - 业务服务层（可编程核心）
FastAPI 与 MCP server 共用此层，不依赖任何传输协议。
推送事件通过 self.notify 回调注入（FastAPI 注入 WS 广播，MCP 可注入自己的通知或置空）。
"""
import csv
import hashlib
import logging
import sqlite3
import time
import uuid
from bisect import bisect_left, bisect_right
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from .state import StateManager
from .script_engine import ScriptEngine
from .datasource import DataSourceManager
from .results import normalize_result, next_result_id, summarize, slice_section
from .store import Store
from . import optimizer as opt
from ..backtest import runner as engine_runner

logger = logging.getLogger("agentkline.service")


def _to_ms(v):
    """时间戳秒→毫秒自适应：|v|<1e11 视为秒（epoch_s），×1000；否则视为已是毫秒。"""
    if v is None:
        return None
    v = int(v)
    return v * 1000 if abs(v) < 10**11 else v


class AgentKlineService:
    """AgentKline 业务核心"""

    VERSION = "0.6.5"

    def __init__(self, scripts_dir: str, limits: dict = None, data_dir: str = None):
        limits = limits or {}
        self.state = StateManager()
        self.script_engine = ScriptEngine(scripts_dir)
        self.datasource = DataSourceManager(self.state, self.script_engine, self)
        from .watchlist import WatchlistManager
        self.watchlist = WatchlistManager(self, poll_s=limits.get("quotes_poll_s", 5))
        # v0.6.3 现场库：给 data_dir 才落盘（测试/一次性实例保持纯内存）
        self.data_dir = Path(data_dir).expanduser() if data_dir else None
        self.store = None
        if self.data_dir:
            try:
                self.store = Store(self.data_dir / "state.db", app_version=self.VERSION)
            except (OSError, sqlite3.Error):
                # 目录不可写/磁盘故障：降级纯内存，别让一块烂盘把服务挡在门外
                logger.exception("现场库打开失败，本次运行降级为纯内存（不落盘）")
            else:
                self.state.restore(self.store)
                self.watchlist.attach(self.store)
        # R8 性能三件套限额（config limits 可覆盖）
        self.max_window = int(limits.get("max_window", 5000))
        # (board, tf) -> 已确认没有更早数据时的最早时间戳；有新增历史会自动失效
        self._backfill_exhausted: dict = {}
        self.max_bars_per_slot = int(limits.get("max_bars_per_slot", 50000))
        self.state.MAX_BARS_PER_SLOT = self.max_bars_per_slot
        self.init_window = int(limits.get("init_window", 2000))
        self._symbol_index: dict = {}  # script_id -> {"ts": epoch, "symbols": [...]}
        self._index_building: set = set()
        import threading as _th
        self._index_building_lock = _th.Lock()
        self.SYMBOL_INDEX_TTL = 86400  # 索引 TTL 日级；手动 refresh 可强刷
        self.DEFAULT_ONLINE_TFS = ["15m", "1h", "4h", "1d", "1w"]  # 实时源建板默认周期
        self.notify: Callable[[dict], None] = lambda msg: None  # 由传输层注入
        self.current_view: dict = {}  # 用户当前视图（前端上报）
        # v0.6.4 参数矩阵作业（内存态；结果本身落盘，重启只丢 job 不丢结果）
        self.matrix_max_runs = int(limits.get("matrix_max_runs", 60))
        self._matrix_jobs: dict[str, dict] = {}
        self._matrix_lock = _th.Lock()
        # v0.6.5 参数寻优作业（内存态；只把 Top K 的样本外结果登记进结果栏）
        self.optimize_max_runs = int(limits.get("optimize_max_runs", 200))
        self._optimize_jobs: dict[str, dict] = {}
        self._optimize_lock = _th.Lock()

    def _build_index(self, sid):
        """建单源索引（防重入：warmup 与搜索请求撞车不重复建）。返回 True=建成/已有，False=他人构建中。"""
        import threading as _th
        with self._index_building_lock:
            if sid in self._index_building:
                return False
            self._index_building.add(sid)
        try:
            r = self.script_engine.list_symbols(sid, "")
            if isinstance(r, dict) and r.get("error"):
                logger.warning("索引构建失败 %s: %s", sid, r["error"])
                return True
            import time as _t
            self._symbol_index[sid] = {"ts": _t.time(),
                                       "symbols": r.get("symbols") if isinstance(r, dict) else r}
            return True
        except Exception as e:
            logger.warning("索引构建异常 %s: %s", sid, e)
            return True
        finally:
            with self._index_building_lock:
                self._index_building.discard(sid)

    def _refresh_expired(self, sids):
        for sid in sids:
            self._build_index(sid)  # 防重入；刷好即换，搜索无感

    def warmup_symbol_index(self):
        """v0.4.4 启动预热：后台并行建全源索引（不阻塞启动；把重启后首搜的一次性等待吸收进启动）。"""
        from concurrent.futures import ThreadPoolExecutor
        sids = [x["id"] for x in self.script_engine.list_scripts()
                if x["kind"] == "datasource" and x["caps"].get("symbols")]
        logger.info("索引预热开始: %s", sids)
        with ThreadPoolExecutor(max_workers=max(1, len(sids))) as ex:
            list(ex.map(self._build_index, sids))
        logger.info("索引预热完成: %s", {k: len(v.get("symbols") or []) for k, v in self._symbol_index.items()})

    def _symbol_display(self, sid, symbol):
        """搜索索引里的 display（如 '浦发银行 600000'）；索引未建/无该 symbol → None。"""
        ent = self._symbol_index.get(sid or "")
        if not ent:
            return None
        for x in ent.get("symbols") or []:
            if x.get("symbol") == symbol:
                return x.get("display")
        return None

    def restore_market(self):
        """v0.6.3 重启恢复：按 source_lock 逐槽重拉 K 线并起轮询（后台线程调用）。
        源不可达不阻塞启动：该槽保持配置，轮询线程后续自愈。"""
        if self.store is None:
            return
        boards = [b for b in self.state.list_boards() if b.get("locked")]
        logger.info("恢复行情：%d 个锁定板", len(boards))
        for b in boards:
            board = self.state.get_board(b["id"])
            if board is None:
                continue
            for tf in list(board.timeframes.keys()):
                try:
                    r = self._configure_slot(b["id"], tf)
                    if r.get("error"):
                        logger.warning("恢复槽 %s:%s 失败: %s", b["id"], tf, r["error"])
                except Exception as exc:
                    logger.warning("恢复槽 %s:%s 异常: %s", b["id"], tf, exc)
        logger.info("行情恢复结束")

    # ============ 画板 ============
    def create_board(self, board_id, name=None, intervals=None, symbol=None,
                     source=None, params=None, poll_s=None):
        """建板。给 symbol/source = 建板即锁（用户侧搜索流）；皆无 = 空板（仅 AI 可建）。"""
        if (symbol or source) and not name:
            # 默认名 = 显示链统一格式：源名: 标的名（去 kind/ 前缀）
            # v0.4.4：display 优先（中文名等，搜索索引查得）；查不到回落 symbol——
            # 加密源无索引/无 display → 与现状同，通用性零特判
            stem = str(source).split("/")[-1] if source else ""
            label = self._symbol_display(source, symbol) or symbol
            name = f"{stem}: {label}" if (stem and label) else (label or stem or None)
        if (symbol or source) and not intervals:
            # 实时源建板默认五周期 = [15m,1h,4h,1d,1w] ∩ 脚本 INTERVALS；离线源(未声明)保持单槽自由
            meta = self.script_engine.metadata(source) if source else {}
            supported = (meta or {}).get("intervals") if isinstance(meta, dict) else None
            if supported:
                intervals = [d for d in self.DEFAULT_ONLINE_TFS if d in supported] or list(supported)
        if symbol or source:
            # 同锁幂等 get-or-create：同(源,identity)现场已存在 → 直接返回该板（连点/重复搜索不产重复板）
            if not source:
                return {"error": "LOCK_REQUIRES_SOURCE: 建板即锁需同时给 source（脚本 id）"}
            full_params = {**(params or {})}
            if symbol:
                full_params.setdefault("symbol", symbol)
            id_keys = (self.script_engine.metadata(source) or {}).get("identity") or []
            missing = [k for k in id_keys if k not in full_params]
            if not missing:
                want = {k: full_params[k] for k in id_keys}
                for b in self.state.list_boards():
                    lk = b.get("source_lock") or {}
                    if lk.get("script") == source and lk.get("identity") == want:
                        return {"id": b["id"], "name": b.get("name"), "existing": True,
                                "intervals": b.get("intervals"), "source_lock": lk}
        result = self.state.create_board(board_id, name, intervals)
        if result.get("error"):
            return result
        if symbol or source:
            full_params = {**(params or {})}
            if symbol:
                full_params.setdefault("symbol", symbol)
            lock_err = self._lock_board(board_id, source, full_params)
            if lock_err:
                self.state.delete_board(board_id)
                return lock_err
            board = self.state.get_board(board_id)
            try:
                r = self.set_kline_source(board_id, board.current_timeframe, source,
                                          full_params, poll_s, fetch_timeout=10)
            except Exception as e:
                r = {"error": f"SOURCE_FETCH_ERROR: {e}"}
            if r.get("error"):
                self.datasource.stop_sync(board_id, board.current_timeframe)
                self.state.delete_board(board_id)
                return r
            # v0.4.4：其余初始槽后台线程配置（建板响应不等网络；槽由轮询线程填数自愈）
            import threading as _th
            _rest = [tf for tf in board.intervals if tf != board.current_timeframe]
            if _rest:
                def _bg_cfg():
                    errs = {}
                    for tf in _rest:
                        try:
                            rr = self._configure_slot(board_id, tf, poll_s)
                            if rr.get("error"):
                                errs[tf] = rr["error"]
                        except Exception as e:
                            errs[tf] = str(e)
                    if errs:
                        logger.warning("create_board 后台槽配置失败: %s", errs)
                _th.Thread(target=_bg_cfg, daemon=True, name=f"cfg-{board_id}").start()
            result = {**result, "source_lock": board.source_lock}
        self._bc({"type": "board_create", "board": result})
        return result

    def _lock_board(self, board_id, script, params) -> Optional[dict]:
        """首配锁：identity 快照 = IDENTITY 键 → params 值；缺键报错"""
        if self.script_engine.resolve(script) is None:
            return {"error": f"SCRIPT_NOT_FOUND: {script}"}
        meta = self.script_engine.metadata(script)
        id_keys = meta.get("identity") or []
        missing = [k for k in id_keys if k not in params]
        if missing:
            return {"error": f"LOCK_INCOMPLETE: 脚本 IDENTITY 键 {missing} 未在 params 提供（如 symbol）"}
        board = self.state.get_board(board_id)
        board.source_lock = {"script": script, "identity": {k: params[k] for k in id_keys}}
        if self.store is not None:
            # 锁是板配置的一部分（重启后按它重拉行情），改完立即落盘
            self.state._p_board(board)
            self.state._p(self.store.log_event, "board_lock",
                          {"board": board_id, "script": script}, board_id)
        self._bc({"type": "board_locked", "board_id": board_id,
                  "source_lock": board.source_lock})
        return None

    def _locked_err(self, board, script, params) -> dict:
        """SOURCE_LOCKED：错误文案即教育 + 结构化 suggestion（一键改道建板）"""
        lock = board.source_lock
        ident = lock.get("identity") or {}
        return {
            "error": (f"SOURCE_LOCKED: 该画板已锁定 "
                      f"{ident.get('symbol', '')}@{lock['script']}，请求的 "
                      f"{params.get('symbol') or script} 未配置；换标的/换源请新建画板"),
            "code": "SOURCE_LOCKED",
            "suggestion": {"action": "create_board", "symbol": params.get("symbol"),
                           "script": script, "params": params},
        }

    def list_boards(self):
        return {"boards": self.state.list_boards()}

    def switch_board(self, board_id):
        result = self.state.switch_board(board_id)
        if not result.get("error"):
            tf = self.state.get_default_timeframe(board_id)
            self._poke_if_stale(board_id, tf)
            self._bc({"type": "board_switch", "board_id": board_id, "timeframe": tf,
                      "state": self.get_state_windowed(board_id, tf)})
        return result

    def update_board(self, board_id, data):
        return self.state.update_board(board_id, data)

    def delete_board(self, board_id):
        # 先停该板所有槽轮询+清配置（防孤儿轮询继续打脚本/广播）
        board = self.state.get_board(board_id)
        if board:
            for tf in list(board.timeframes.keys()):
                self.datasource.stop_sync(board_id, tf)
        result = self.state.delete_board(board_id)
        if not result.get("error"):
            self._bc({"type": "board_remove", "board_id": board_id,
                      "current_board": self.state.current_board_id})
            # v0.4：删光最后一个板 = 全白户 → 前端落引导页（搜索流建现场），不再自动补空板
        return result

    # ============ 时间周期 ============
    def create_timeframe(self, board_id, interval):
        board = self.state.get_board(board_id)
        if board and board.source_lock:
            meta = self.script_engine.metadata(board.source_lock["script"])
            supported = (meta or {}).get("intervals")
            if supported and interval not in supported:
                return {"error": f"INTERVAL_UNSUPPORTED: {board.source_lock['script']} 不支持 "
                                 f"{interval}（支持: {supported}）"}
        result = self.state.create_timeframe(board_id, interval)
        if result.get("error"):
            return result
        self._bc({"type": "timeframe_create", "board_id": board_id, "interval": interval})
        board = self.state.get_board(board_id)
        if board and board.source_lock:
            # 在线板：新周期槽由系统自动注入 {script, identity + interval}，用户点"+"即可出图
            r = self._configure_slot(board_id, interval)
            if r.get("error"):
                return r
        return result

    def _configure_slot(self, board_id, tf, poll_s=None):
        """在线板槽位自动注入配置 {script, identity+interval}；poll_s 缺省继承已有槽"""
        board = self.state.get_board(board_id)
        if not board or not board.source_lock:
            return {"status": "ok"}
        if poll_s is None:
            for x in board.timeframes:
                cfg = self.datasource.configs.get(self.datasource._key(board_id, x))
                if cfg and cfg.get("poll_s"):
                    poll_s = cfg["poll_s"]
                    break
        params = {**board.source_lock["identity"], "interval": tf}
        return self.set_kline_source(board_id, tf, board.source_lock["script"], params, poll_s)

    def delete_timeframe(self, board_id, tf):
        result = self.state.delete_timeframe(board_id, tf)
        if not result.get("error"):
            self._bc({"type": "timeframe_remove", "board_id": board_id, "interval": tf,
                      "default_timeframe": result.get("default_timeframe")})
            # 删除最后一个周期 → 自动补默认 1d，保证画板永远有周期
            board = self.state.boards.get(board_id)
            if board is not None and not board.intervals:
                self.create_timeframe(board_id, "1d")
                self.switch_timeframe(board_id, "1d")
        return result

    def list_timeframes(self, board_id):
        return self.state.list_timeframes(board_id)

    def _poke_if_stale(self, board_id, tf):
        """性能①配套：切到的槽若老于降频窗 → 立即补拉（用户无感）"""
        from datetime import datetime as _dt
        key = self.datasource._key(board_id, tf)
        cfg = self.datasource.configs.get(key)
        if not cfg or cfg.get("mode") != "poll":
            return
        st = self.datasource.status.get(key) or {}
        lf = st.get("last_fetch")
        stale = True
        if lf:
            try:
                age = (_dt.now() - _dt.fromisoformat(lf)).total_seconds()
                stale = age > self.datasource._decay_s(tf)
            except ValueError:
                stale = True
        if stale:
            self.datasource.poke(board_id, tf)

    def switch_timeframe(self, board_id, tf):
        result = self.state.switch_timeframe(board_id, tf)
        if not result.get("error"):
            # 懒配置：在线板切到未配置槽 → 自动注入（治愈存量空槽/任何漏配路径）
            board = self.state.get_board(board_id)
            cfg = self.datasource.configs.get(self.datasource._key(board_id, tf))
            if board and board.source_lock and not cfg:
                self._configure_slot(board_id, tf)
            self._poke_if_stale(board_id, tf)
            self._bc({"type": "timeframe_switch", "board_id": board_id, "timeframe": tf,
                      "state": self.get_state_windowed(board_id, tf)})
        return result

    # ============ K线 ============
    def set_ohlcv(self, board_id, timeframe, ohlcv, markers=None):
        prev = self.state.get_ohlcv(board_id, timeframe)
        result = self.state.set_ohlcv(board_id, timeframe, ohlcv, markers)
        if not result.get("error"):
            # 指标实例按 scope 自动覆盖本周期（登记处语义，无需 propagate）
            self.recompute_indicators(board_id, timeframe)
            self.bc_ohlcv_delta(board_id, timeframe, prev, ohlcv, markers=markers or [])
        return result

    def bc_ohlcv_delta(self, board_id, tf, prev, new, markers=None):
        """R8 传输增量化：ohlcv_update 只推差量（前插/追加/尾部更新），前端按 ts 合并"""
        prev = prev or []
        pmap = {b["timestamp"]: b for b in prev}
        first = prev[0]["timestamp"] if prev else None
        last = prev[-1]["timestamp"] if prev else None
        prepended, appended, updated = [], [], []
        for b in new:
            ts = b["timestamp"]
            if ts not in pmap:
                if first is not None and ts < first:
                    prepended.append(b)
                else:
                    appended.append(b)
            elif pmap[ts] != b:
                updated.append(b)
        payload = {"board_id": board_id, "timeframe": tf,
                   "prepended": prepended, "appended": appended, "updated": updated}
        if markers is not None:
            payload["markers"] = markers
        self._bc({"type": "ohlcv_update", **payload})

    def get_state_windowed(self, board_id, timeframe, window=None):
        """init/switch 携带窗口=最近 N 根（非全树）；左滚历史走 backfill 按需"""
        st = self.state.get_timeframe_state(board_id, timeframe)
        # 画线属于板：随 init/switch 一并下发（切周期不重新装载，Vela 按 showOn 过滤）
        st["drawings"] = self.state.list_drawings(board_id)
        w = window or self.init_window
        if st.get("ohlcv") and len(st["ohlcv"]) > w:
            st = {**st, "ohlcv": st["ohlcv"][-w:], "windowed": True}
        return st

    def search_symbols(self, q: str = "", refresh: bool = False, source: str = None) -> dict:
        """标的搜索（P1）：索引=CAPS.symbols 源首用全量+TTL 日级+手动 refresh；
        搜索永不穿透交易所（首用后本地过滤）。行=完整二元组(源,裸符号)+●现场徽标"""
        import time as _t
        q = (q or "").strip().upper()
        rows, errors = [], []
        cands = [s for s in self.script_engine.list_scripts()
                 if s["kind"] == "datasource" and s["caps"].get("symbols")
                 and (not source or s["id"] == source)]  # v0.4.4 源筛选：50 截断前过滤
        now0 = _t.time()
        # v0.4.4 stale-while-revalidate：过期源=旧索引继续服务+后台刷新（用户永撞不到重建等待；
        # 索引是符号+名字清单，旧一天几乎零害；手动 refresh 仍同步=显式要新）
        expired = [s["id"] for s in cands
                   if not refresh and self._symbol_index.get(s["id"])
                   and (now0 - self._symbol_index[s["id"]]["ts"]) > self.SYMBOL_INDEX_TTL]
        if expired:
            import threading as _th
            _th.Thread(target=self._refresh_expired, args=(expired,), daemon=True,
                       name="index-refresh").start()
        # 冷态（无索引/手动 refresh）：并行构建 + 每源 8s 超时（单源烂网不拖全局）
        stale = [s["id"] for s in cands
                 if (refresh or self._symbol_index.get(s["id"]) is None)
                 and s["id"] not in expired]
        if stale:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TE
            def _build(sid):
                return sid, self._build_index(sid)
            ex = ThreadPoolExecutor(max_workers=len(stale))
            futs = {ex.submit(_build, sid): sid for sid in stale}
            for f in futs:
                sid = futs[f]
                try:
                    _, ok = f.result(timeout=8)
                except _TE:
                    errors.append({sid: "INDEX_BUILD_TIMEOUT: 索引构建超 8s（源网络限流窗？稍后重试）"})
                    continue
                except Exception as e:
                    errors.append({sid: str(e)[:120]})
                    continue
                if ok is False:
                    errors.append({sid: "INDEX_WARMING: 索引后台构建中，稍后重试"})
            # v0.4.4：wait=False——超时源线程让它自己跑完死掉，绝不拖搜索响应
            ex.shutdown(wait=False, cancel_futures=True)
        for s in cands:
            sid = s["id"]
            ent = self._symbol_index.get(sid)
            if not ent:
                continue
            now = _t.time()
            for sym in ent["symbols"]:
                symbol, display = sym.get("symbol"), sym.get("display") or sym.get("symbol")
                if q and q not in str(symbol).upper() and q not in str(display).upper():
                    continue
                has_board = any(
                    b.source_lock and b.source_lock["script"] == sid
                    and (b.source_lock.get("identity") or {}).get("symbol") == symbol
                    for b in self.state.boards.values())
                rows.append({"symbol": symbol, "source": sid, "display": display,
                             "has_board": has_board,
                             "watched": self.watchlist.has_row(sid, symbol)})
                if len(rows) >= 50:
                    break
            if len(rows) >= 50:
                break
        # v0.4.4：随响应附 symbols 徽章源清单（前端筛选 chips 用；web 端口不开放 /api/scripts）
        srcs = [x["id"] for x in self.script_engine.list_scripts()
                if x["kind"] == "datasource" and x["caps"].get("symbols")]
        return {"rows": rows, "errors": errors, "sources": srcs}

    def set_markers(self, board_id, timeframe, markers):
        markers = list(markers or [])
        dropped = []
        bars = self.state.get_ohlcv(board_id, timeframe)
        if bars:  # 有K线才做范围校验；越界丢弃并回报，不静默吞掉
            lo, hi = bars[0]["timestamp"], bars[-1]["timestamp"]
            kept = []
            for m in markers:
                t = m.get("time")
                if t is not None and lo <= t <= hi:
                    kept.append(m)
                else:
                    dropped.append({"time": t, "reason": "out_of_range"})
            markers = kept
        result = self.state.set_markers(board_id, timeframe, markers)
        if not result.get("error"):
            self._bc({"type": "markers_update", "board_id": board_id, "timeframe": timeframe,
                      "markers": markers})
            if dropped:
                result["dropped"] = dropped
        return result

    # ============ 指标 ============
    def run_script(self, script: str, params: dict = None) -> dict:
        """通用脚本执行（v0.4 窄身）：script 为 id（kind/name）；只执行并返回结果，
        图上不留痕。指标落盘 = save_script + add_indicator(script=...)；
        K线入图 = 数据源配方（set_kline_source），皆可溯源可重放。"""
        return self.script_engine.run_script(script, params or {})

    # ============ 指标实例（v0.4：登记处 + 物化缓存，inst_id 把手） ============
    def add_indicator(self, board_id, timeframe, inst_id=None, values=None, subplot=None,
                      style=None, type=None, markers=None, lines=None,
                      script=None, params=None, scope=None, display_name=None):
        """加指标（统一入口，inst_id 把手版）。
        - 计算型 recipe：给 script（id）+params，随K线自动重算
        - 冻结 blob：给 values/lines/markers，钉死本周期（传 scope 直接报 BLOB_SCOPE）
        - inst_id 撞名报 INST_EXISTS；不传自动 macd_2 式生成"""
        if script and (values is not None or lines):
            return {"error": "INDICATOR_BOTH: script(计算型) 与 values/lines(现成型) 互斥"}
        if not script and values is None and not lines and not markers:
            return {"error": "EMPTY_INDICATOR: 需要 script（计算型）或 values/lines（现成型）"}
        board = self.state.get_board(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        kind = "recipe" if script else "blob"
        if kind == "blob" and scope is not None:
            return {"error": "BLOB_SCOPE: 冻结 blob 钉死单周期，不能传 scope（存在性推论）"}
        if script and self.script_engine.resolve(script) is None:
            from .script_engine import id_error
            return {"error": id_error(script) if "/" not in str(script)
                    else f"SCRIPT_NOT_FOUND: {script}"}
        # v0.4.3 bug1 修：副图族脚本声明 SUBPLOT → 未显式传 subplot 时自动归属（单一真相=脚本元数据）
        if script and subplot is None:
            meta = self.script_engine.metadata(script) or {}
            if meta.get("subplot"):
                subplot = str(script).split("/")[-1]
        scope = scope or ("board" if kind == "recipe" else "timeframe")
        if inst_id and self.state.get_instance(board_id, inst_id):
            return {"error": f"INST_EXISTS: inst_id '{inst_id}' 已存在（换一个或用 update_indicator 改）",
                    "code": "INST_EXISTS"}
        if not inst_id:
            base = script.split("/")[-1] if script else "blob"
            inst_id, n = base, 2
            while self.state.get_instance(board_id, inst_id):
                inst_id, n = f"{base}_{n}", n + 1
        # v0.4.3：recipe 空 params 填脚本 PARAMS 默认（实例参数永远完整，设置面板有得渲染）
        if kind == "recipe" and not params:
            meta = self.script_engine.metadata(script) or {}
            params = dict(meta.get("params") or {})
        inst = {"inst_id": inst_id, "kind": kind, "script": script,
                "params": params or {}, "scope": scope,
                "tf": None if scope == "board" else timeframe,
                "target": subplot, "style": style, "lines_style": None,
                "visible": True,   # P2-fix：显隐服务端真源（刷新持久 + 多端一致）
                "display_name": display_name, "custom_label": bool(display_name),
                "auto_label": None,
                "blob": None if kind == "recipe" else
                        {"values": values, "lines": lines, "markers": markers}}
        self.state.add_instance(board_id, inst)
        targets = self._all_timeframes(board_id) if scope == "board" else [timeframe]
        for tf in targets:
            if subplot:
                self._ensure_subplot(board_id, tf, subplot)
            if kind == "recipe":
                self._recompute_one(board_id, tf, inst)
            else:
                b = inst["blob"]
                self.state.set_cache(board_id, tf, inst_id,
                                     b.get("values"), b.get("lines"), b.get("markers"))
                inst["auto_label"] = inst_id
        self._bc_indicators("indicator_add", board_id, targets, inst)
        return {"status": "ok", "inst_id": inst_id, "scope": scope}

    def _recompute_one(self, board_id, tf, inst):
        """重算单个 recipe 实例（尾窗 max_window 截尾喂脚本，warmup 由脚本自留）"""
        ohlcv = self.state.get_ohlcv(board_id, tf)
        if not ohlcv:
            return
        win = getattr(self, "max_window", 5000)
        feed = ohlcv[-win:] if len(ohlcv) > win else ohlcv
        result = self.script_engine.run_indicator_script(inst["script"], feed, inst.get("params"))
        if result.get("error"):
            logger.warning("recompute %s/%s %s: %s", board_id, tf, inst["inst_id"], result["error"])
            return
        # P1 时间戳契约：values 时间轴 = feed bar ts（脚本逐 bar 对齐 feed，warmup 补 None 亦天然同长）
        times = [b["timestamp"] for b in feed]
        self.state.set_cache(board_id, tf, inst["inst_id"],
                             result.get("values"), result.get("lines"), result.get("markers"),
                             times=times, levels=result.get("levels"),
                             polylines=result.get("polylines"))
        if not inst.get("custom_label"):
            inst["auto_label"] = self._auto_label(inst, result.get("meta"))

    def _auto_label(self, inst, meta):
        meta = meta or {}
        if meta.get("label"):
            return meta["label"]
        root = (meta.get("name") or str(inst["script"]).split("/")[-1]).upper()
        vals = [str(v) for v in (inst.get("params") or {}).values()]
        if len(vals) > 3:
            vals = vals[:3] + ['…']
        return f"{root}({', '.join(vals)})" if vals else root

    def recompute_indicators(self, board_id, timeframe):
        """本周期全部 recipe 实例重算（K线更新/回溯/换源统一入口）；blob 不动"""
        board = self.state.get_board(board_id)
        if not board:
            return
        changed = [i for i in self.state.tf_instances(board_id, timeframe)
                   if i["kind"] == "recipe"]
        for inst in changed:
            self._recompute_one(board_id, timeframe, inst)
        if changed:
            self._bc_indicators("indicator_update", board_id, [timeframe], None, insts=changed)

    def _bc_indicators(self, ev_type, board_id, tfs, inst, insts=None):
        """广播指标变化（wire：inst_id + recipe 摘要 + 物化值）"""
        items = insts or ([inst] if inst else [])
        for tf in tfs:
            for it in items:
                c = self.state.get_cache(board_id, tf, it["inst_id"]) or {}
                self._bc({"type": ev_type, "board_id": board_id, "timeframe": tf,
                          "inst_id": it["inst_id"], "kind": it["kind"],
                          "display_name": it.get("display_name") or it.get("auto_label") or it["inst_id"],
                          "subplot": it["target"], "style": it["style"],
                          "lines_style": it["lines_style"], "params": it["params"],
                          "scope": it["scope"], "script": it["script"],
                          "values": c.get("values"), "lines": c.get("lines"),
                          "markers": c.get("markers"), "times": c.get("times"),
                          "levels": c.get("levels"), "polylines": c.get("polylines"),
                          "visible": it.get("visible", True)})

    def delete_indicator(self, board_id, timeframe, inst_id):
        inst = self.state.get_instance(board_id, inst_id)
        r = self.state.delete_instance(board_id, inst_id)
        if r.get("error"):
            return r
        for tf in self._all_timeframes(board_id):
            self._bc({"type": "indicator_remove", "board_id": board_id,
                      "timeframe": tf, "inst_id": inst_id})
        # v0.4.3 bug1 配套：自动副图无人用即回收（命名约定=script stem；手工同名副图极低概率误收）
        target = (inst or {}).get("target")
        script = (inst or {}).get("script") or ""
        if target and target == str(script).split("/")[-1]:
            still = any(i.get("target") == target
                        for i in self.state.list_instances(board_id))
            if not still:
                for tf in self._all_timeframes(board_id):
                    self.state.delete_subplot(board_id, tf, target)
                    self._bc({"type": "subplot_remove", "board_id": board_id,
                              "timeframe": tf, "name": target})
        return {"status": "ok", "inst_id": inst_id}

    def refresh_indicator(self, board_id, timeframe, inst_id):
        inst = self.state.get_instance(board_id, inst_id)
        if not inst:
            return {"error": f"Indicator '{inst_id}' not found"}
        if inst["kind"] != "recipe":
            return {"error": "Indicator 是冻结 blob，不可重算"}
        self._recompute_one(board_id, timeframe, inst)
        self._bc_indicators("indicator_update", board_id, [timeframe], inst)
        return {"status": "ok", "inst_id": inst_id}

    def update_indicator(self, board_id, timeframe, inst_id, params=None, style=None,
                         lines_style=None, display_name=None, auto_label=None, visible=None):
        """统一更新：改参数=重声明配方并重算；改样式=不重算；显示名可覆盖/恢复自动；
        visible=显隐（服务端真源，刷新持久，不重算）"""
        inst = self.state.get_instance(board_id, inst_id)
        if not inst:
            return {"error": f"Indicator '{inst_id}' not found"}
        patch = {}
        if visible is not None:
            patch["visible"] = bool(visible)
        if style is not None:
            patch["style"] = style
        if lines_style is not None:
            patch["lines_style"] = lines_style
        if display_name is not None:
            patch.update(display_name=display_name, custom_label=True)
        if auto_label:
            patch.update(display_name=None, custom_label=False)
        recompute = False
        if params is not None:
            if inst["kind"] != "recipe":
                return {"error": "Blob 无配方，不能改 params"}
            patch["params"] = {**(inst.get("params") or {}), **params}
            recompute = True
        if patch:
            self.state.update_instance(board_id, inst_id, patch)
        targets = self._all_timeframes(board_id) if inst["scope"] == "board" \
            else [inst.get("tf") or timeframe]
        if recompute:
            for tf in targets:
                self._recompute_one(board_id, tf, inst)
        if lines_style:
            for tf in targets:
                c = self.state.get_cache(board_id, tf, inst_id)
                for ln in (c or {}).get("lines") or []:
                    ls = lines_style.get(ln.get("name"))
                    if ls:
                        ln.setdefault("style", {}).update(ls)
        self._bc_indicators("indicator_update", board_id, targets, inst)
        return {"status": "ok", "inst_id": inst_id,
                "display_name": inst.get("display_name") or inst.get("auto_label") or inst_id}

    # ============ 结果实例（v0.6.0） ============
    def _script_sha(self, ref):
        """脚本内容哈希（结果可复现指纹）；取不到返回空串。"""
        try:
            r = self.script_engine.resolve(ref) if ref else None
            if not r or not r.get("path"):
                return ""
            return hashlib.sha256(open(r["path"], "rb").read()).hexdigest()
        except Exception:
            return ""

    def _next_result_id(self, strategy_id: str) -> str:
        """结果 id 全局唯一：/api/result/{id} 不带 board 参数，跨板撞 id 会取错结果。"""
        existing = {}
        for b in self.state.boards.values():
            existing.update(dict.fromkeys(b.results))
        return next_result_id(existing, strategy_id)

    def import_result(self, payload):
        """导入一份外部/引擎结果：校验、补算口径、冻结、广播。"""
        if not isinstance(payload, dict):
            return {"error": "RESULT_INVALID: payload 需要 JSON 对象"}
        board_id = payload.get("board_id") or self.state.current_board_id
        board = self.state.get_board(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        tf = payload.get("timeframe") or board.current_timeframe
        tf_state = board.get_tf(tf)
        bars = tf_state.ohlcv if tf_state else []
        lock = board.source_lock or {}
        ident = lock.get("identity") or {}
        out = normalize_result(
            payload, board_id, tf, bars=bars, version=self.VERSION,
            source_sha256=self._script_sha(lock.get("script")),
            symbol=ident.get("symbol"), source_script=lock.get("script") or "")
        if out.get("error"):
            return out
        res = out["result"]
        res["result_id"] = self._next_result_id(res["strategy"]["id"])
        r = self.state.add_result(board_id, res)
        if r.get("error"):
            return r
        summary = summarize(res)
        self._bc_result_created(board_id, tf, summary, r)
        out_body = {"status": "ok", "result": summary,
                    "warnings": out.get("warnings") or []}
        if r.get("evicted"):
            out_body["evicted"] = r["evicted"]
        return out_body

    def _bc_result_created(self, board_id, tf, summary, add_out):
        """结果落库后的广播：先删被自动淘汰的旧结果，再宣布新结果。"""
        from .results import MAX_RESULTS_PER_BOARD
        for ev in add_out.get("evicted") or []:
            self._bc({"type": "result_deleted", "board_id": board_id, "timeframe": tf,
                      "result_id": ev["result_id"], "evicted": True,
                      "display_name": ev.get("display_name"),
                      "created_at": ev.get("created_at"),
                      "limit": MAX_RESULTS_PER_BOARD})
        self._bc({"type": "result_created", "board_id": board_id,
                  "timeframe": tf, "result": summary})

    @staticmethod
    def _data_fingerprint(bars, start_idx=0):
        """轻量数据指纹（O(1) 校验）：窗口首尾时间 + 根数 + 两端收盘。"""
        win = bars[start_idx:] if start_idx else bars
        if not win:
            return None
        try:
            return {"from": int(win[0]["timestamp"]), "to": int(win[-1]["timestamp"]),
                    "bars": len(win),
                    "head_close": round(float(win[0]["close"]), 8),
                    "tail_close": round(float(win[-1]["close"]), 8)}
        except (KeyError, TypeError, ValueError):
            return None

    def _freshness(self, res, cache):
        """把结果里记的指纹与当前 K 线比对，判断是否“基于旧快照”。"""
        data = res.get("data") or {}
        fp = data.get("fingerprint")
        if not fp:
            return None            # 0.6.4 之前的结果没有指纹：不猜
        board_id, tf = data.get("board"), data.get("timeframe")
        key = (board_id, tf)
        if key not in cache:
            bars = self.state.get_ohlcv(board_id, tf) or []
            cache[key] = ([int(b["timestamp"]) for b in bars], bars)
        ts, bars = cache[key]
        if not ts:
            return {"stale": True, "reason": "NO_DATA"}
        i0 = bisect_left(ts, int(fp["from"]))
        if i0 >= len(ts) or ts[i0] != int(fp["from"]):
            return {"stale": True, "reason": "HEAD_MOVED"}
        i1 = bisect_right(ts, int(fp["to"])) - 1
        if i1 < i0 or ts[i1] != int(fp["to"]):
            return {"stale": True, "reason": "TAIL_MOVED"}
        if (i1 - i0 + 1) != int(fp.get("bars") or 0):
            return {"stale": True, "reason": "BAR_COUNT"}
        try:
            head = round(float(bars[i0]["close"]), 8)
            tail = round(float(bars[i1]["close"]), 8)
        except (KeyError, TypeError, ValueError):
            return {"stale": True, "reason": "BAR_INVALID"}
        if head != fp.get("head_close") or tail != fp.get("tail_close"):
            return {"stale": True, "reason": "PRICE_REVISED"}
        return {"stale": False, "reason": ""}

    def list_results(self, board_id=None, timeframe=None):
        rows = self.state.list_results(board_id, timeframe)
        cache = {}
        for row in rows:
            fr = self._freshness(row, cache)
            if fr:
                row["freshness"] = fr
        out = {"board_id": board_id, "count": len(rows), "results": rows}
        if board_id:
            from .results import MAX_RESULTS_PER_BOARD
            board = self.state.get_board(board_id)
            used = len(board.results) if board else 0
            out["retention"] = {
                "limit": MAX_RESULTS_PER_BOARD, "count": used,
                "warn_at": max(1, MAX_RESULTS_PER_BOARD - 10),
                "evict_next": max(0, used - MAX_RESULTS_PER_BOARD + 1),
            }
        return out

    def get_result(self, result_id, section="summary", offset=0, limit=200):
        res = (self.state.get_result(result_id) if section == "summary"
               else self.state.hydrate_result(result_id))
        if not res:
            return {"error": f"Result '{result_id}' not found"}
        return slice_section(res, section, offset, limit)

    def rename_result(self, result_id, display_name):
        r = self.state.rename_result(result_id, display_name)
        if r.get("error"):
            return r
        res = self.state.get_result(result_id)
        if res:
            self._bc({"type": "result_updated", "board_id": res["data"]["board"],
                      "timeframe": res["data"]["timeframe"], "result": summarize(res)})
        return r

    def delete_result(self, result_id):
        res = self.state.get_result(result_id)
        if not res:
            return {"error": f"Result '{result_id}' not found"}
        board_id, tf = res["data"]["board"], res["data"]["timeframe"]
        r = self.state.delete_result(result_id)
        if r.get("error"):
            return r
        self._bc({"type": "result_deleted", "board_id": board_id,
                  "timeframe": tf, "result_id": result_id})
        return r

    def focus_result_trade(self, result_id, trade_index=0):
        """v0.6.4 运镜原语：把用户屏幕带到某条结果的某一笔交易。

        只发广播（选中结果 → 打开详情 → 选中该笔 → 图上定位），不改结果。
        没有浏览器在线时报 NO_BROWSER（同快照语义，不假装成功）。
        """
        res = self.state.hydrate_result(result_id)
        if not res:
            return {"error": f"Result '{result_id}' not found"}
        trades = res.get("trades") or []
        try:
            idx = int(trade_index)
        except (TypeError, ValueError):
            return {"error": "INPUT_INVALID: trade_index 需为整数"}
        if idx < 0 or idx >= len(trades):
            return {"error": f"TRADE_NOT_FOUND: trade_index {idx} 越界（共 {len(trades)} 笔）"}
        if not self._ws_active():
            return {"error": "NO_BROWSER: 运镜需要已打开的 Web UI（/ws 无连接）"}
        tr = trades[idx]
        data = res.get("data") or {}
        self._bc({"type": "result_focus", "result_id": result_id, "trade_index": idx,
                  "board_id": data.get("board"), "timeframe": data.get("timeframe"),
                  "entry_time": tr.get("entry_time"), "exit_time": tr.get("exit_time"),
                  "display_name": res.get("display_name")})
        return {"status": "ok", "result_id": result_id, "trade_index": idx,
                "trade_count": len(trades), "trade": tr}

    # ============ 参数方案（v0.6.4 收尾：独立于结果的参数集） ============
    def _preset_scope(self, board_id):
        """方案作用域 = 数据源 + 标的（取自板锁）；空板没有标的，不能存方案。"""
        board = self.state.get_board(board_id)
        if not board:
            return None, {"error": f"Board '{board_id}' not found"}
        lock = board.source_lock or {}
        ident = lock.get("identity") or {}
        if not (lock.get("script") and ident.get("symbol")):
            return None, {"error": "PRESET_REQUIRES_LOCK: 参数方案绑定标的，请先在已锁定画板上保存"
                                   "（空板先配数据源）"}
        return {"source": lock["script"], "symbol": ident["symbol"],
                "board_id": board_id, "timeframe": board.current_timeframe or ""}, None

    def _preset_params(self, script, params):
        """按策略声明校验并补全默认值：存完整参数，应用时可直接填表单。"""
        meta = self.strategy_meta(script=script)
        if not meta.get("ok"):
            return None, {"error": f"PRESET_INVALID: 策略声明不可用（{meta.get('error') or script}）"}
        defaults = meta.get("params") or {}
        pmeta = meta.get("param_meta") or {}
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return None, {"error": "PRESET_INVALID: params 需要对象"}
        unknown = [k for k in params if k not in defaults]
        if unknown:
            return None, {"error": f"PRESET_INVALID: 未知参数 {unknown}（可用: {list(defaults)}）"}
        clean = {}
        for k, v in params.items():
            val, err = self._matrix_cast(k, v, defaults.get(k), pmeta.get(k))
            if err:
                return None, {"error": err.replace("MATRIX_INVALID", "PRESET_INVALID")}
            clean[k] = val
        return {**defaults, **clean}, None

    def list_presets(self, board_id=None, script=None):
        if self.store is None:
            return {"error": "PRESET_UNAVAILABLE: 现场库未启用，参数方案需要落盘"}
        scope = None
        if board_id:
            scope, err = self._preset_scope(board_id)
            if err:
                return err
        rows = self.store.list_presets(
            scope["source"] if scope else None,
            scope["symbol"] if scope else None,
            (script or None))
        for row in rows:
            # v0.6.5：策略内容变了就提示“参数可能不再对应”；旧方案没哈希时先不猜
            stored = row.get("script_sha256") or ""
            current = self._script_sha(row.get("script")) if stored else ""
            row["script_changed"] = bool(stored and current and stored != current)
        return {"board_id": board_id, "count": len(rows), "presets": rows}

    def save_preset(self, board_id, name, params=None, script=None, timeframe=None,
                    note=None, origin_result_id=None, is_default=False):
        if self.store is None:
            return {"error": "PRESET_UNAVAILABLE: 现场库未启用，参数方案需要落盘"}
        scope, err = self._preset_scope(board_id)
        if err:
            return err
        origin = None
        if origin_result_id:
            res = self.state.hydrate_result(origin_result_id)
            if not res:
                return {"error": f"Result '{origin_result_id}' not found"}
            st = res.get("strategy") or {}
            if params is None:
                params = st.get("params") or {}
            script = script or st.get("id")
            timeframe = timeframe or ((res.get("data") or {}).get("timeframe") or "")
            origin = {"result_id": origin_result_id,
                      "batch_id": (res.get("batch") or {}).get("id"),
                      "display_name": res.get("display_name"),
                      "created_at": res.get("created_at"),
                      "window": (res.get("run") or {}).get("window"),
                      "stats": res.get("stats"),
                      "fingerprint": (res.get("data") or {}).get("fingerprint")}
        script = str(script or "").strip()
        if not script:
            return {"error": "PRESET_SCRIPT_REQUIRED: 需要 script（strategy/xxx）或 origin_result_id"}
        merged, werr = self._preset_params(script, params)
        if werr:
            return werr
        nm = str(name or "").strip()
        if not nm:
            return {"error": "PRESET_NAME_EMPTY: 方案名不能为空"}
        nm = nm[:80]
        tf = str(timeframe if timeframe is not None
                 else (self.state.get_board(board_id).current_timeframe or "")) or ""
        dup = [p for p in self.store.list_presets(scope["source"], scope["symbol"], script, tf)
               if p["name"] == nm]
        if dup:
            return {"error": f"PRESET_EXISTS: 已有同名方案「{nm}」（id={dup[0]['id']}）"}
        same = [p for p in self.store.list_presets(scope["source"], scope["symbol"], script, tf)
                if p["params"] == merged]
        if same:
            return {"error": f"PRESET_DUPLICATE_PARAMS: 这组参数已存为「{same[0]['name']}」"
                             f"（id={same[0]['id']}），无需重复保存"}
        preset = {"id": f"ps_{uuid.uuid4().hex[:8]}", "source": scope["source"],
                  "symbol": scope["symbol"], "timeframe": tf, "script": script,
                  "name": nm, "params": merged, "note": note, "origin": origin,
                  "script_sha256": self._script_sha(script),
                  "is_default": bool(is_default)}
        self.store.insert_preset(preset)
        if is_default:
            self.store.set_default_preset(preset["id"])
        preset = self.store.get_preset(preset["id"])
        preset["script_changed"] = False
        self._bc({"type": "preset_changed", "board_id": board_id, "preset": preset})
        return {"status": "ok", "preset": preset}

    def update_preset(self, preset_id, name=None, params=None, note=None,
                      is_default=None):
        if self.store is None:
            return {"error": "PRESET_UNAVAILABLE: 现场库未启用，参数方案需要落盘"}
        preset = self.store.get_preset(preset_id)
        if not preset:
            return {"error": f"Preset '{preset_id}' not found"}
        patch = {}
        if name is not None:
            nm = str(name).strip()
            if not nm:
                return {"error": "PRESET_NAME_EMPTY: 方案名不能为空"}
            others = [p for p in self.store.list_presets(
                preset["source"], preset["symbol"], preset["script"], preset["timeframe"])
                if p["name"] == nm and p["id"] != preset_id]
            if others:
                return {"error": f"PRESET_EXISTS: 已有同名方案「{nm}」（id={others[0]['id']}）"}
            patch["name"] = nm[:80]
        if params is not None:
            merged, err = self._preset_params(preset["script"], params)
            if err:
                return err
            same = [p for p in self.store.list_presets(
                preset["source"], preset["symbol"], preset["script"], preset["timeframe"])
                if p["params"] == merged and p["id"] != preset_id]
            if same:
                return {"error": f"PRESET_DUPLICATE_PARAMS: 这组参数已存为「{same[0]['name']}」"
                                 f"（id={same[0]['id']}），无需重复保存"}
            patch["params"] = merged
            # 参数按当前策略重新校验过 → 同步刷新哈希基线
            patch["script_sha256"] = self._script_sha(preset["script"])
        if note is not None:
            patch["note"] = note
        if is_default is not None:
            patch["is_default"] = bool(is_default)
        self.store.update_preset(preset_id, patch)
        if is_default:
            self.store.set_default_preset(preset_id)
        preset = self.store.get_preset(preset_id)
        stored = preset.get("script_sha256") or ""
        current = self._script_sha(preset["script"]) if stored else ""
        preset["script_changed"] = bool(stored and current and stored != current)
        self._bc({"type": "preset_changed", "board_id": None, "preset": preset})
        return {"status": "ok", "preset": preset}

    def delete_preset(self, preset_id):
        if self.store is None:
            return {"error": "PRESET_UNAVAILABLE: 现场库未启用，参数方案需要落盘"}
        preset = self.store.get_preset(preset_id)
        if not preset:
            return {"error": f"Preset '{preset_id}' not found"}
        self.store.delete_preset(preset_id)
        self._bc({"type": "preset_deleted", "preset_id": preset_id})
        return {"status": "ok", "preset_id": preset_id}

    # ============ 引擎回测（v0.6.1 M3：只走 ak-engine 子进程） ============
    def list_strategies(self):
        """策略脚本清单（web 只读；exec 的 list_scripts 在 agent 端口）。"""
        rows = [r for r in self.script_engine.list_scripts() if r.get("kind") == "strategy"]
        return {"strategies": rows}

    def list_engines(self):
        """引擎清单。后端不 import 引擎运行时，清单也来自子进程。"""
        try:
            return {"engines": engine_runner.list_engines()}
        except engine_runner.EngineRunError as exc:
            return {"error": f"{exc.code}: {exc.message}", **exc.to_dict()}

    def _strategy_source(self, script=None, source=None):
        """策略源码：内联 source 优先，否则按 strategy/xxx 读脚本。"""
        if source:
            return str(source), None
        if not script:
            return None, "STRATEGY_REQUIRED: 需要 script（strategy/xxx）或 source"
        r = self.script_engine.resolve(script)
        if not r:
            return None, f"SCRIPT_NOT_FOUND: {script}"
        try:
            return r["path"].read_text(encoding="utf-8-sig"), None
        except OSError as exc:
            return None, f"SCRIPT_NOT_FOUND: 读取 {script} 失败: {exc}"

    def strategy_meta(self, script=None, source=None):
        """策略声明（NAME/DESC/WARMUP/PARAMS/PARAM_META/PROTECTION）+ AST 校验。"""
        src, err = self._strategy_source(script, source)
        if err:
            return {"ok": False, "error": err}
        try:
            from agentkline_engine.loader import describe_source
        except Exception:  # pragma: no cover - 精简安装
            return {"ok": False, "error": "ENGINE_UNAVAILABLE: 引擎框架未安装"}
        info = describe_source(src)
        return {"ok": not info["errors"], "script": script or "", **info}

    BACKFILL_CHUNK = 1000
    MAX_BACKFILL_CALLS = 40

    def _ensure_history(self, board_id, tf, start_ms, want, warmup, budget_s):
        """按需补历史：默认补到 want+warmup 根；给了 start 则补到 start 之前 warmup 根。

        补到数据源 genesis 或预算用完为止；返回实际补进来的根数。
        """
        target = start_ms
        need = warmup if start_ms is not None else want + warmup
        if need <= 0:
            return 0
        pulled = 0
        t0 = time.monotonic()
        exhausted_at = self._backfill_exhausted.get((board_id, tf))
        for _ in range(self.MAX_BACKFILL_CALLS):
            bars = self.state.get_ohlcv(board_id, tf) or []
            have = len(bars) if target is None else sum(
                1 for b in bars if int(b["timestamp"]) < int(target))
            if have >= need:
                break
            if exhausted_at is not None and bars and int(bars[0]["timestamp"]) == exhausted_at:
                break
            if time.monotonic() - t0 > budget_s:
                logger.info("run_backtest 补历史超预算（%.1fs），用现有 %d 根", budget_s, len(bars))
                break
            chunk = self.BACKFILL_CHUNK
            try:
                r = self.backfill(board_id, tf, limit=chunk)
            except Exception as exc:  # pragma: no cover - 数据源异常不阻塞回测
                logger.warning("run_backtest 补历史失败: %s", exc)
                break
            n = int(r.get("prepended") or 0)
            if n <= 0:
                # 记住"已到最早"，避免每次回测都白跑一次数据源请求
                head = self.state.get_ohlcv(board_id, tf) or []
                if head:
                    self._backfill_exhausted[(board_id, tf)] = int(head[0]["timestamp"])
                break
            pulled += n
        return pulled

    @staticmethod
    def _slice_window(bars, start_ms, end_ms, want, warmup):
        """按时间/根数切窗口；窗口前留 warmup 根给指标预热。返回 (bars, lead, error)。"""
        if not bars:
            return None, 0, "NO_BARS: 该周期没有可用的 K 线"
        if end_ms is not None:
            end_idx = next((i for i in range(len(bars) - 1, -1, -1)
                            if int(bars[i]["timestamp"]) <= int(end_ms)), None)
            if end_idx is None:
                return None, 0, "INPUT_INVALID: 结束时间早于最早一根 K 线"
        else:
            end_idx = len(bars) - 1
        if start_ms is not None:
            start_idx = next((i for i, b in enumerate(bars)
                              if int(b["timestamp"]) >= int(start_ms)), None)
            if start_idx is None:
                return None, 0, "INPUT_INVALID: 开始时间晚于最后一根 K 线"
        else:
            start_idx = max(0, end_idx - want + 1)
        if start_idx > end_idx:
            return None, 0, "INPUT_INVALID: 时间范围内没有 K 线"
        lead = min(max(warmup, 0), start_idx)
        window = bars[start_idx - lead:end_idx + 1]
        if len(window) <= lead:
            return None, 0, "INPUT_INVALID: 时间范围内没有可评估的 K 线"
        return window, lead, None

    def _run_context(self, board_id, timeframe=None, engine="builtin", script=None,
                     source=None, params=None, direction="long_only",
                     initial_cash=10000.0, fee_bps=5.0, slippage_bps=5.0,
                     protection=None, start_time=None, end_time=None, limit=20000,
                     backfill_budget=20.0):
        """一次回测的「准备段」：校验 → 策略声明 → 补历史 → 冻结窗口。

        v0.6.4：参数矩阵复用同一份 ctx（同一批 bars），保证各组结果可比。
        返回 ctx 或 {"error": ...}。
        """
        if direction not in ("long_only", "short_only", "both"):
            return {"error": f"INPUT_INVALID: direction 需为 long_only/short_only/both，收到 {direction!r}"}
        try:
            cash = float(initial_cash)
            fee = float(fee_bps)
            slip = float(slippage_bps)
        except (TypeError, ValueError):
            return {"error": "INPUT_INVALID: initial_cash/fee_bps/slippage_bps 必须是数字"}
        if cash <= 0:
            return {"error": "INPUT_INVALID: initial_cash 必须 > 0"}
        if fee < 0 or slip < 0:
            return {"error": "INPUT_INVALID: fee_bps/slippage_bps 不能为负"}

        board = self.state.get_board(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        tf = timeframe or board.current_timeframe
        if not (board.get_tf(tf) and board.get_tf(tf).ohlcv):
            return {"error": "NO_BARS: 该周期还没有已载入的 K 线，先等行情加载完再回测"}

        src, err = self._strategy_source(script, source)
        if err:
            return {"error": err}

        # 策略声明：显示名/warmup/默认保护（纯 AST，不执行）
        try:
            from agentkline_engine.loader import describe_source
            info = describe_source(src)
        except Exception:  # pragma: no cover - 精简安装
            info = {}
        merged_params = {**(info.get("params") or {}), **(params or {})}
        merged_prot = {**(info.get("protection") or {}), **(protection or {})}
        warmup = int(info.get("warmup") or 0)

        # 时间窗口：可选；默认最新往回 limit 根
        try:
            want = int(limit if limit is not None else 20000)
        except (TypeError, ValueError):
            return {"error": "INPUT_INVALID: limit 必须是整数（回溯根数）"}
        if want < 100:
            return {"error": "INPUT_INVALID: limit 至少 100 根"}
        want = min(want, 50000)
        start_ms = _to_ms(start_time) if start_time is not None else None
        end_ms = _to_ms(end_time) if end_time is not None else None
        try:
            budget = max(0.0, float(backfill_budget if backfill_budget is not None else 20.0))
        except (TypeError, ValueError):
            budget = 20.0
        backfilled = self._ensure_history(board_id, tf, start_ms, want, warmup, budget)
        bars, lead, werr = self._slice_window(
            [dict(b) for b in (self.state.get_ohlcv(board_id, tf) or [])],
            start_ms, end_ms, want, warmup)
        if werr:
            return {"error": werr}
        # 引擎口径：eval_start = max(请求的窗口起点, 策略 WARMUP)；历史不够时实际起点会晚于请求
        eval_idx = max(lead, warmup)
        if eval_idx >= len(bars) - 1:
            return {"error": f"EVAL_WINDOW_EMPTY: 可用 {len(bars)} 根，不够指标预热（WARMUP={warmup}）"}
        clipped = bool(start_ms is not None and int(bars[eval_idx]["timestamp"]) > int(start_ms))
        return {
            "board_id": board_id, "tf": tf, "engine": engine,
            "script": script, "source": source, "src": src, "info": info,
            "merged_params": merged_params, "merged_prot": merged_prot,
            "protection_override": protection,
            "warmup": warmup, "cash": cash, "fee": fee, "slip": slip,
            "direction": direction, "start_ms": start_ms, "end_ms": end_ms,
            "want": want, "backfilled": backfilled,
            "bars": bars, "eval_idx": eval_idx, "clipped": clipped,
        }

    def _execute_run(self, ctx, params=None, timeout=120.0, display_name=None, batch=None,
                     register=True):
        """用已冻结的 ctx 跑一次引擎并登记结果（单跑与矩阵共用）。

        register=False 时只算不登记（寻优试次用；Top K 才会二次登记进结果栏）。
        """
        board_id, tf = ctx["board_id"], ctx["tf"]
        bars, eval_idx = ctx["bars"], ctx["eval_idx"]
        cash, fee, slip = ctx["cash"], ctx["fee"], ctx["slip"]
        merged_params = {**ctx["merged_params"], **(params or {})}
        run_in = {
            "initial_cash": cash, "fee_bps": fee, "slippage_bps": slip,
            "direction": ctx["direction"],
            # 窗口前的 warmup 根只给策略预热，不计绩效也不交易
            "eval_start": eval_idx,
            "params": params or {},
        }
        if ctx["protection_override"]:
            run_in["protection"] = ctx["protection_override"]
        spec = {"api": 1, "engine": ctx["engine"], "bars": bars,
                "strategy": {"source": ctx["src"]}, "run": run_in, "timeframe": tf}
        try:
            payload = engine_runner.run_spec(spec, timeout=float(timeout))
        except engine_runner.EngineRunError as exc:
            return {"error": f"{exc.code}: {exc.message}", **exc.to_dict()}

        elapsed_ms = int(payload.pop("_elapsed_ms", 0) or 0)
        eq = payload.get("equity") or {}
        times = [int(t) for t in (eq.get("times") or [])]
        values = [float(v) for v in (eq.get("values") or [])]
        if not times or len(times) != len(values):
            return {"error": "RESULT_INVALID: 引擎没有返回可用的权益序列"}
        if abs(values[0] - cash) > max(1e-6, abs(cash) * 1e-6):
            # eval_start > WARMUP 时首点带仓：补一个初始资金锚点，满足结果契约
            idx = next((i for i, b in enumerate(bars)
                        if int(b["timestamp"]) >= times[0]), 0)
            anchor = int(bars[idx - 1]["timestamp"]) if idx > 0 else times[0] - 1
            times = [anchor] + times
            values = [cash] + values

        asm = payload.get("assumptions") or {}
        eng = payload.get("engine") or {}
        info = ctx["info"] or {}
        result_payload = {
            "board_id": board_id,
            "timeframe": tf,
            "status": payload.get("status"),
            "equity": {"times": times, "values": values},
            "trades": payload.get("trades") or [],
            "fills": payload.get("fills") or [],
            "warnings": payload.get("warnings") or [],
            "runtime_ms": elapsed_ms,
            "run": {
                "initial_cash": cash, "fee": fee / 10_000.0, "slippage": slip / 10_000.0,
                "leverage": 1.0, "bars_per_year": asm.get("bars_per_year"),
            },
            "engine": {
                "id": str(eng.get("id") or ctx["engine"]),
                "version": str(eng.get("version") or ""),
                "caps": eng.get("caps") if isinstance(eng.get("caps"), dict) else {},
                "config": {"api": 1, "direction": ctx["direction"], "fee_bps": fee,
                           "slippage_bps": slip, "params": params or {}},
            },
            "strategy": {
                "id": ctx["script"] or "strategy/inline",
                "mode": "signal",
                "params": merged_params,
                "warmup": int(info.get("warmup") or 0),
                "protection": ctx["merged_prot"],
                "source": ctx["src"],
            },
            "execution_assumptions": asm,
            "data": {"requested": {"from": bars[eval_idx]["timestamp"],
                                   "to": bars[-1]["timestamp"]}},
            "display_name": display_name or (info.get("name") or "").strip() or None,
            "units": {},
        }
        lock = self.state.get_board(board_id).source_lock or {}
        out = normalize_result(
            result_payload, board_id, tf, bars=bars, version=self.VERSION,
            source_sha256=self._script_sha(ctx["script"]) if ctx["script"] else "",
            symbol=(lock.get("identity") or {}).get("symbol"),
            source_script=ctx["script"] or "",
        )
        if out.get("error"):
            return out
        res = out["result"]
        res["data"]["fingerprint"] = self._data_fingerprint(bars, eval_idx)
        if batch:
            res["batch"] = batch          # 加法字段：批次归属（随 summary 落盘，不建表）
        if not register:
            return {"status": "ok", "result": summarize(res),
                    "warnings": out.get("warnings") or [],
                    "run": {"engine": result_payload["engine"]["id"],
                            "elapsed_ms": elapsed_ms, "bars": len(bars) - eval_idx,
                            "from": bars[eval_idx]["timestamp"], "to": bars[-1]["timestamp"],
                            "warmup_bars": eval_idx, "backfilled": ctx["backfilled"],
                            "clipped": ctx["clipped"],
                            "requested": {"start": ctx["start_ms"], "end": ctx["end_ms"],
                                          "limit": ctx["want"]}}}
        res["result_id"] = self._next_result_id(res["strategy"]["id"])
        r = self.state.add_result(board_id, res)
        if r.get("error"):
            return r
        summary = summarize(res)
        self._bc_result_created(board_id, tf, summary, r)
        body = {
            "status": "ok",
            "result": summary,
            "warnings": out.get("warnings") or [],
            "run": {"engine": result_payload["engine"]["id"],
                    "elapsed_ms": elapsed_ms, "bars": len(bars) - eval_idx,
                    "from": bars[eval_idx]["timestamp"], "to": bars[-1]["timestamp"],
                    "warmup_bars": eval_idx, "backfilled": ctx["backfilled"],
                    "clipped": ctx["clipped"],
                    "requested": {"start": ctx["start_ms"], "end": ctx["end_ms"],
                                  "limit": ctx["want"]}},
        }
        if r.get("evicted"):
            body["evicted"] = r["evicted"]
        return body

    def run_backtest(self, board_id, timeframe=None, engine="builtin", script=None,
                     source=None, params=None, direction="long_only",
                     initial_cash=10000.0, fee_bps=5.0, slippage_bps=5.0,
                     protection=None, start_time=None, end_time=None, limit=20000,
                     backfill_budget=20.0, timeout=120.0):
        """跑一次回测：确定窗口（必要时补历史）→ 子进程 → 校验/补算 → 登记结果 + 广播。

        窗口：start_time/end_time 可选；缺省 = 最新往回 limit 根（默认 2 万）。
        历史不够时先按数据源能力回补；再往前没有数据就用现有的。"""
        ctx = self._run_context(
            board_id, timeframe=timeframe, engine=engine, script=script, source=source,
            params=params, direction=direction, initial_cash=initial_cash,
            fee_bps=fee_bps, slippage_bps=slippage_bps, protection=protection,
            start_time=start_time, end_time=end_time, limit=limit,
            backfill_budget=backfill_budget)
        if ctx.get("error"):
            return ctx
        return self._execute_run(ctx, params, timeout=timeout)

    # ============ 参数矩阵（v0.6.4：同一份数据上跑一组参数） ============
    @staticmethod
    def _matrix_cast(key, value, default, meta):
        """把 grid 值收敛到参数类型并做区间校验；返回 (canonical, err)。"""
        return opt.cast_value(key, value, default, meta, prefix="MATRIX_INVALID")

    def _matrix_expand(self, info, grid, params_list):
        """展开参数矩阵（默认值基底 + 覆盖）。返回 (combos, err)。"""
        import itertools
        base = dict((info or {}).get("params") or {})
        meta = dict((info or {}).get("param_meta") or {})
        if params_list is not None:
            if not isinstance(params_list, list) or not params_list:
                return None, "MATRIX_EMPTY: params_list 需要非空数组"
            raw = []
            for item in params_list:
                if not isinstance(item, dict):
                    return None, "MATRIX_INVALID: params_list 的元素需要对象"
                unknown = [k for k in item if k not in base]
                if unknown:
                    return None, (f"MATRIX_INVALID: 未知参数 {unknown}（可用: {list(base) or '无'}）")
                raw.append(dict(item))
        else:
            grid = grid or {}
            if not isinstance(grid, dict) or not grid:
                return None, "MATRIX_EMPTY: 至少给 grid 或 params_list"
            unknown = [k for k in grid if k not in base]
            if unknown:
                return None, (f"MATRIX_INVALID: 未知参数 {unknown}（可用: {list(base) or '无'}）")
            keys = list(grid)
            for k in keys:
                if not isinstance(grid[k], list) or not grid[k]:
                    return None, f"MATRIX_EMPTY: grid.{k} 需要非空数组"
            raw = [dict(zip(keys, values))
                   for values in itertools.product(*[grid[k] for k in keys])]
        if len(raw) > self.matrix_max_runs:
            return None, (f"MATRIX_LIMIT: 组合 {len(raw)} 超过上限 {self.matrix_max_runs}"
                          f"（拆小或调 limits.matrix_max_runs）")
        combos = []
        for item in raw:
            combo = {}
            for k, v in item.items():
                value, err = self._matrix_cast(k, v, base.get(k), meta.get(k))
                if err:
                    return None, err
                combo[k] = value
            combos.append(combo)
        return combos, None

    def _matrix_label(self, ctx, combo):
        base = ((ctx.get("info") or {}).get("name") or "").strip() \
            or str(ctx.get("script") or "回测").split("/")[-1]
        if not combo:
            return base
        parts = ", ".join(f"{k}={v}" for k, v in combo.items())
        return f"{base} · {parts}"[:120]

    def _matrix_prune(self):
        """作业态内存回收：完成态保留 10 分钟，最多留 20 个。"""
        now = time.time()
        alive = []
        for jid, job in list(self._matrix_jobs.items()):
            done = job.get("status") in ("done", "cancelled", "failed")
            if done and now - float(job.get("finished_at") or 0) > 600:
                self._matrix_jobs.pop(jid, None)
            else:
                alive.append((float(job.get("created_at") or 0), jid))
        if len(self._matrix_jobs) > 20:
            alive.sort()
            for _, jid in alive[:max(0, len(alive) - 20)]:
                self._matrix_jobs.pop(jid, None)

    def run_matrix(self, board_id, timeframe=None, engine="builtin", script=None,
                   source=None, grid=None, params_list=None, direction="long_only",
                   initial_cash=10000.0, fee_bps=5.0, slippage_bps=5.0,
                   protection=None, start_time=None, end_time=None, limit=20000,
                   backfill_budget=20.0, timeout=120.0):
        """参数矩阵：一次冻结窗口，串行跑多组参数，结果逐条登记并广播进度。

        返回 {job_id,total,runs:[{index,params,display_name}]}；进度用
        GET /api/backtest/matrix/{job_id} 或 WS matrix_progress 取。
        """
        ctx = self._run_context(
            board_id, timeframe=timeframe, engine=engine, script=script, source=source,
            params=None, direction=direction, initial_cash=initial_cash,
            fee_bps=fee_bps, slippage_bps=slippage_bps, protection=protection,
            start_time=start_time, end_time=end_time, limit=limit,
            backfill_budget=backfill_budget)
        if ctx.get("error"):
            return ctx
        combos, err = self._matrix_expand(ctx.get("info"), grid, params_list)
        if err:
            return {"error": err}
        job_id = f"mtx_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        runs = [{"index": i, "params": c, "display_name": self._matrix_label(ctx, c)}
                for i, c in enumerate(combos)]
        job = {
            "job_id": job_id, "status": "running", "created_at": time.time(),
            "finished_at": None, "total": len(combos), "done": 0, "current": None,
            "results": [], "errors": [], "cancel": False,
            "board_id": board_id, "timeframe": ctx["tf"], "script": ctx["script"] or "",
            "grid": grid, "params_list": params_list,
            "ctx": ctx, "combos": combos, "timeout": timeout,
        }
        with self._matrix_lock:
            self._matrix_prune()
            self._matrix_jobs[job_id] = job
        self._bc({"type": "matrix_started", "job_id": job_id, "board_id": board_id,
                  "timeframe": ctx["tf"], "total": len(combos), "runs": runs})
        th = __import__("threading").Thread(target=self._matrix_worker, args=(job_id,),
                                            daemon=True, name=f"matrix-{job_id}")
        th.start()
        return {"status": "ok", "job_id": job_id, "total": len(combos),
                "runs": runs, "max_runs": self.matrix_max_runs}

    def _matrix_worker(self, job_id):
        job = self._matrix_jobs.get(job_id)
        if not job:
            return
        ctx = job["ctx"]
        total = job["total"]
        try:
            for i, combo in enumerate(job["combos"]):
                if job.get("cancel"):
                    break
                job["current"] = combo
                self._bc({"type": "matrix_progress", "job_id": job_id,
                          "board_id": job["board_id"], "timeframe": job["timeframe"],
                          "done": job["done"], "total": total, "current": combo})
                batch = {"id": job_id, "index": i, "total": total,
                         "params": combo, "grid": job.get("grid")}
                try:
                    body = self._execute_run(ctx, combo, timeout=job.get("timeout") or 120.0,
                                             display_name=self._matrix_label(ctx, combo),
                                             batch=batch)
                except Exception as exc:  # 单组异常不炸整批
                    body = {"error": f"MATRIX_RUN_FAILED: {exc}"}
                if body.get("error"):
                    job["errors"].append({"index": i, "params": combo,
                                          "error": body["error"]})
                else:
                    res = body.get("result") or {}
                    job["results"].append({"index": i, "result_id": res.get("result_id"),
                                           "params": combo,
                                           "stats": res.get("stats") or {}})
                job["done"] = i + 1
                self._bc({"type": "matrix_progress", "job_id": job_id,
                          "board_id": job["board_id"], "timeframe": job["timeframe"],
                          "done": job["done"], "total": total, "current": combo})
        finally:
            job["status"] = "cancelled" if job.get("cancel") else "done"
            job["finished_at"] = time.time()
            job["current"] = None
            self._bc({"type": "matrix_done", "job_id": job_id,
                      "board_id": job["board_id"], "timeframe": job["timeframe"],
                      "status": job["status"], "total": total, "done": job["done"],
                      "result_ids": [r["result_id"] for r in job["results"]],
                      "errors": job["errors"]})

    def get_matrix(self, job_id):
        job = self._matrix_jobs.get(job_id)
        if not job:
            return {"error": f"MATRIX_JOB_NOT_FOUND: {job_id}"}
        return {
            "job_id": job["job_id"], "status": job["status"],
            "board_id": job["board_id"], "timeframe": job["timeframe"],
            "script": job["script"], "total": job["total"], "done": job["done"],
            "current": job["current"], "results": job["results"],
            "errors": job["errors"], "cancelled": job["status"] == "cancelled",
            "created_at": job["created_at"], "finished_at": job["finished_at"],
        }

    def cancel_matrix(self, job_id):
        job = self._matrix_jobs.get(job_id)
        if not job:
            return {"error": f"MATRIX_JOB_NOT_FOUND: {job_id}"}
        if job["status"] != "running":
            return {"status": job["status"], "noop": True}
        job["cancel"] = True
        return {"status": "ok", "cancelling": True, "done": job["done"],
                "total": job["total"]}

    # ============ 参数寻优（v0.6.5：目标 + 约束 + 样本外验证） ============
    OPTIMIZE_METHODS = ("grid", "random", "bayes")

    def _opt_label(self, ctx, params, suffix=""):
        base = ((ctx.get("info") or {}).get("name") or "").strip() \
            or str(ctx.get("script") or "回测").split("/")[-1]
        parts = ", ".join(f"{k}={v}" for k, v in (params or {}).items())
        text = f"{base} · {parts}" if parts else base
        if suffix:
            text = f"{text} · {suffix}"
        return text[:120]

    def _opt_prune(self):
        """寻优作业态内存回收：完成态保留 10 分钟，最多留 20 个。"""
        now = time.time()
        alive = []
        for jid, job in list(self._optimize_jobs.items()):
            done = job.get("status") in ("done", "cancelled", "failed")
            if done and now - float(job.get("finished_at") or 0) > 600:
                self._optimize_jobs.pop(jid, None)
            else:
                alive.append((float(job.get("created_at") or 0), jid))
        if len(self._optimize_jobs) > 20:
            alive.sort()
            for _, jid in alive[:max(0, len(alive) - 20)]:
                self._optimize_jobs.pop(jid, None)

    @staticmethod
    def _opt_budget(budget, cap):
        if budget is None:
            b = {}
        elif isinstance(budget, (int, float)) and not isinstance(budget, bool):
            b = {"max_runs": budget}
        elif isinstance(budget, dict):
            b = budget
        else:
            return None, "OPTIMIZE_BUDGET_INVALID: budget 需要 {max_runs,max_seconds}"
        extra = [k for k in b if k not in ("max_runs", "max_seconds")]
        if extra:
            return None, f"OPTIMIZE_BUDGET_INVALID: 不认识的键 {extra}"
        try:
            max_runs = int(b.get("max_runs", opt.DEFAULT_BUDGET["max_runs"]))
            max_seconds = float(b.get("max_seconds", opt.DEFAULT_BUDGET["max_seconds"]))
        except (TypeError, ValueError):
            return None, "OPTIMIZE_BUDGET_INVALID: max_runs/max_seconds 需要数字"
        if max_runs < 2:
            return None, "OPTIMIZE_BUDGET_INVALID: max_runs 至少 2"
        if max_runs > cap:
            return None, f"OPTIMIZE_BUDGET_LIMIT: max_runs={max_runs} 超过上限 {cap}"
        if not (10 <= max_seconds <= 3600):
            return None, "OPTIMIZE_BUDGET_INVALID: max_seconds 需在 10~3600"
        return {"max_runs": max_runs, "max_seconds": max_seconds}, None

    @staticmethod
    def _opt_holdout(holdout):
        if holdout is None:
            h = {}
        elif isinstance(holdout, dict):
            h = holdout
        else:
            return None, "OPTIMIZE_HOLDOUT_INVALID: holdout 需要 {ratio,top_k}"
        extra = [k for k in h if k not in ("ratio", "top_k")]
        if extra:
            return None, f"OPTIMIZE_HOLDOUT_INVALID: 不认识的键 {extra}"
        try:
            ratio = float(h.get("ratio", opt.DEFAULT_HOLDOUT["ratio"]))
            top_k = int(h.get("top_k", opt.DEFAULT_HOLDOUT["top_k"]))
        except (TypeError, ValueError):
            return None, "OPTIMIZE_HOLDOUT_INVALID: ratio/top_k 需要数字"
        if ratio < 0 or ratio > 0.5:
            return None, "OPTIMIZE_HOLDOUT_INVALID: ratio 需在 0~0.5（0=不做样本外）"
        if not (1 <= top_k <= 10):
            return None, "OPTIMIZE_HOLDOUT_INVALID: top_k 需在 1~10"
        return {"ratio": ratio, "top_k": top_k}, None

    def run_optimization(self, board_id, timeframe=None, engine="builtin", script=None,
                         source=None, space=None, method="grid", objective=None,
                         constraints=None, budget=None, holdout=None, seed=None,
                         direction="long_only", initial_cash=10000.0, fee_bps=5.0,
                         slippage_bps=5.0, protection=None, start_time=None,
                         end_time=None, limit=20000, backfill_budget=20.0,
                         timeout=120.0):
        """参数寻优：冻结窗口 → 按空间/方法逐组回测 → Top K 做样本外验证并登记。

        立即返回 {job_id,...}；进度用 get_optimization 或 WS optimize_progress。
        """
        method = str(method or "grid").lower()
        if method not in self.OPTIMIZE_METHODS:
            return {"error": f"OPTIMIZE_METHOD_INVALID: method 需为 "
                             f"{'/'.join(self.OPTIMIZE_METHODS)}，收到 {method!r}"}
        obj, err = opt.parse_objective(objective)
        if err:
            return {"error": err}
        cons, err = opt.parse_constraints(constraints)
        if err:
            return {"error": err}
        bud, err = self._opt_budget(budget, self.optimize_max_runs)
        if err:
            return {"error": err}
        hol, err = self._opt_holdout(holdout)
        if err:
            return {"error": err}
        try:
            seed = int(seed) if seed is not None else int(time.time() * 1000) % (2 ** 32)
        except (TypeError, ValueError):
            return {"error": "OPTIMIZE_INVALID: seed 需要整数"}
        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            return {"error": "OPTIMIZE_INVALID: timeout 需要数字"}
        if timeout <= 0:
            return {"error": "OPTIMIZE_INVALID: timeout 必须 > 0"}

        ctx = self._run_context(
            board_id, timeframe=timeframe, engine=engine, script=script, source=source,
            params=None, direction=direction, initial_cash=initial_cash,
            fee_bps=fee_bps, slippage_bps=slippage_bps, protection=protection,
            start_time=start_time, end_time=end_time, limit=limit,
            backfill_budget=backfill_budget)
        if ctx.get("error"):
            return ctx
        space_out, err = opt.parse_space(ctx.get("info"), space)
        if err:
            return {"error": err}

        if method == "grid":
            combos, err = opt.expand_grid(space_out["values"], bud["max_runs"])
            if err:
                return {"error": err}
            total = len(combos)
        else:
            combos = None
            total = min(bud["max_runs"], int(space_out["size"]))

        n_eval = len(ctx["bars"]) - ctx["eval_idx"]
        is_n, oos_n, err = opt.split_eval_bars(n_eval, hol["ratio"])
        if err:
            return {"error": err}
        is_ctx = ctx
        oos_ctx = None
        split_time = None
        if hol["ratio"] > 0:
            split_abs = ctx["eval_idx"] + is_n
            split_time = int(ctx["bars"][split_abs]["timestamp"])
            is_bars = [dict(b) for b in ctx["bars"][:split_abs]]
            is_ctx = dict(ctx, bars=is_bars, end_ms=split_time - 1,
                          want=len(is_bars) - ctx["eval_idx"])
            lead = min(int(ctx["warmup"]), split_abs)
            oos_bars = [dict(b) for b in ctx["bars"][split_abs - lead:]]
            oos_ctx = dict(ctx, bars=oos_bars, eval_idx=lead,
                           start_ms=int(oos_bars[lead]["timestamp"]),
                           end_ms=int(oos_bars[-1]["timestamp"]),
                           want=len(oos_bars) - lead, clipped=False)
        holdout_meta = {"ratio": hol["ratio"], "top_k": hol["top_k"],
                        "is_bars": is_n, "oos_bars": oos_n, "split_time": split_time}

        job_id = f"opt_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        job = {
            "job_id": job_id, "status": "running", "phase": "is",
            "created_at": time.time(), "finished_at": None, "elapsed_ms": None,
            "board_id": board_id, "timeframe": ctx["tf"], "script": ctx["script"] or "",
            "method": method, "objective": obj, "constraints": cons,
            "budget": bud, "holdout": holdout_meta, "seed": seed,
            "space": space, "space_values": space_out["values"],
            "space_size": int(space_out["size"]), "combos": combos,
            "is_ctx": is_ctx, "oos_ctx": oos_ctx, "total": total, "done": 0,
            "oos_done": 0, "current": None, "trials": [], "top": [], "best": None,
            "warnings": [], "errors": [], "registered_result_ids": [],
            "cancel": False, "space_exhausted": False, "timeout": timeout,
        }
        with self._optimize_lock:
            self._opt_prune()
            self._optimize_jobs[job_id] = job
        self._bc({"type": "optimize_started", "job_id": job_id, "board_id": board_id,
                  "timeframe": ctx["tf"], "method": method, "total": total,
                  "objective": obj, "holdout": holdout_meta})
        th = __import__("threading").Thread(target=self._optimize_worker, args=(job_id,),
                                            daemon=True, name=f"optimize-{job_id}")
        th.start()
        return {"status": "ok", "job_id": job_id, "method": method, "total": total,
                "phase": "is", "space": space_out["values"], "objective": obj,
                "constraints": cons, "budget": bud, "holdout": holdout_meta}

    def _optimize_worker(self, job_id):
        job = self._optimize_jobs.get(job_id)
        if not job:
            return
        rng = __import__("random").Random(job["seed"])
        tried = set()
        observations = []
        t0 = time.monotonic()
        method = job["method"]
        try:
            if method == "grid":
                for i, combo in enumerate(job["combos"]):
                    if job.get("cancel"):
                        break
                    if time.monotonic() - t0 > job["budget"]["max_seconds"]:
                        job["warnings"].append({"code": "TIME_BUDGET",
                                                "message": "达到时间预算，提前结束搜索"})
                        break
                    self._opt_one(job, combo, i)
                    if job["trials"][-1].get("status") == "ok":
                        observations.append({"params": combo,
                                             "score": job["trials"][-1]["score"]})
            else:
                i = 0
                while i < job["total"] and not job.get("cancel"):
                    if time.monotonic() - t0 > job["budget"]["max_seconds"]:
                        job["warnings"].append({"code": "TIME_BUDGET",
                                                "message": "达到时间预算，提前结束搜索"})
                        break
                    if method == "bayes":
                        combo = opt.propose_tpe(job["space_values"], observations, rng, tried)
                    else:
                        combo = opt.next_random(job["space_values"], rng, tried)
                    if combo is None:
                        job["space_exhausted"] = True
                        break
                    tried.add(opt._key(combo))
                    trial = self._opt_one(job, combo, i)
                    if trial.get("status") == "ok":
                        observations.append({"params": combo, "score": trial["score"]})
                    i += 1

            if not job.get("cancel"):
                self._opt_after_search(job)
        except Exception as exc:  # pragma: no cover - 兜底：作业别静默卡 running
            logger.exception("参数寻优作业失败: %s", job_id)
            job["status"] = "failed"
            job["errors"].append({"error": f"OPTIMIZE_FAILED: {exc}"})
            job["warnings"].append({"code": "OPTIMIZE_FAILED",
                                    "message": f"作业异常结束：{exc}"})
        finally:
            if job["status"] == "running":
                job["status"] = "cancelled" if job.get("cancel") else "done"
            job["phase"] = "done"
            job["finished_at"] = time.time()
            job["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
            job["current"] = None
            self._bc({"type": "optimize_done", "job_id": job_id,
                      "board_id": job["board_id"], "timeframe": job["timeframe"],
                      "status": job["status"], "total": job["total"],
                      "done": job["done"], "best": job.get("best"),
                      "result_ids": list(job["registered_result_ids"]),
                      "warnings": job["warnings"]})

    def _opt_one(self, job, combo, index):
        """跑一组样本内试次并写入 job；异常转成 failed 行。"""
        job["current"] = combo
        self._bc({"type": "optimize_progress", "job_id": job["job_id"],
                  "board_id": job["board_id"], "timeframe": job["timeframe"],
                  "phase": "is", "done": job["done"], "total": job["total"],
                  "current": combo})
        try:
            body = self._execute_run(
                job["is_ctx"], combo, timeout=job["timeout"],
                display_name=self._opt_label(job["is_ctx"], combo), register=False)
        except Exception as exc:  # 单组异常不炸整批
            body = {"error": f"OPTIMIZE_RUN_FAILED: {exc}"}
        trial = opt.summarize_trial(index, combo, body, job["objective"],
                                    job["constraints"])
        if (body or {}).get("error"):
            trial["status"] = "failed"
            trial["reason"] = body["error"]
            job["errors"].append({"index": index, "params": combo, "error": body["error"]})
        job["trials"].append(trial)
        job["done"] = int(job.get("done") or 0) + 1
        self._bc({"type": "optimize_progress", "job_id": job["job_id"],
                  "board_id": job["board_id"], "timeframe": job["timeframe"],
                  "phase": "is", "done": job["done"], "total": job["total"],
                  "current": combo, "trial": {k: trial.get(k) for k in
                                               ("index", "status", "score", "value", "reason")}})
        return trial

    def _opt_patch_batch(self, result_id, extra):
        """样本外跑完后补 batch 字段（is_stats 先写、oos_stats 后补），并广播更新。"""
        res = self.state.get_result(result_id)
        if not res:
            return
        res.setdefault("batch", {}).update(extra)
        summary = summarize(res)
        if self.store is not None:
            self.store.update_result_summary(result_id, summary)
        self._bc({"type": "result_updated", "board_id": res["data"]["board"],
                  "timeframe": res["data"]["timeframe"], "result": summary})

    def _opt_after_search(self, job):
        """样本内搜索结束：Top K 做样本外验证并登记（无 holdout 则登记 Top K 样本内）。"""
        top = opt.select_top(job["trials"], job["holdout"]["top_k"])
        if not top:
            job["warnings"].append({"code": "NO_VALID_TRIAL",
                                    "message": "没有满足约束的有效试次，未登记结果"})
            return
        if job["holdout"]["ratio"] > 0:
            job["phase"] = "oos"
            valid = []
            for j, trial in enumerate(top):
                if job.get("cancel"):
                    break
                job["current"] = trial["params"]
                self._bc({"type": "optimize_progress", "job_id": job["job_id"],
                          "board_id": job["board_id"], "timeframe": job["timeframe"],
                          "phase": "oos", "done": j, "total": len(top),
                          "current": trial["params"]})
                batch = {"id": job["job_id"], "kind": "optimize",
                         "method": job["method"], "index": j, "total": len(top),
                         "params": trial["params"], "phase": "oos",
                         "objective": job["objective"],
                         "is_stats": trial.get("is_stats"),
                         "is_score": trial.get("score")}
                try:
                    body = self._execute_run(
                        job["oos_ctx"], trial["params"], timeout=job["timeout"],
                        display_name=self._opt_label(job["is_ctx"], trial["params"], "样本外"),
                        batch=batch)
                except Exception as exc:
                    body = {"error": f"OPTIMIZE_OOS_FAILED: {exc}"}
                if body.get("error"):
                    trial["oos_status"] = "failed"
                    trial["oos_error"] = body["error"]
                    job["errors"].append({"index": trial["index"], "phase": "oos",
                                          "params": trial["params"], "error": body["error"]})
                    job["warnings"].append({"code": "OOS_FAILED", "index": trial["index"],
                                            "message": body["error"]})
                    continue
                res = body.get("result") or {}
                oos_stats = res.get("stats") or {}
                scored = opt.score_stats(oos_stats, job["objective"], job["constraints"])
                over = opt.overfit_check(trial.get("is_stats"), oos_stats, job["objective"])
                trial.update({
                    "oos_status": scored["status"], "oos_score": scored["score"],
                    "oos_value": scored["value"], "oos_reason": scored["reason"],
                    "oos_stats": oos_stats, "overfit_gap": over["gap"],
                    "overfit_ratio": over["ratio"], "result_id": res.get("result_id"),
                    "oos_warnings": over["warnings"],
                })
                if trial.get("result_id"):
                    self._opt_patch_batch(trial["result_id"], {
                        "oos_stats": oos_stats, "oos_score": scored["score"],
                        "oos_value": scored["value"],
                        "overfit_gap": over["gap"], "overfit_ratio": over["ratio"],
                    })
                for w in over["warnings"]:
                    job["warnings"].append({"index": trial["index"], **w})
                if trial.get("result_id"):
                    job["registered_result_ids"].append(trial["result_id"])
                    job["results"] = job.get("results") or []
                    job["results"].append({"index": trial["index"],
                                           "result_id": trial["result_id"],
                                           "params": trial["params"],
                                           "score": trial.get("oos_score"),
                                           "is_stats": trial.get("is_stats"),
                                           "oos_stats": oos_stats})
                if scored["status"] == "ok":
                    valid.append(trial)
                job["oos_done"] = j + 1
                self._bc({"type": "optimize_progress", "job_id": job["job_id"],
                          "board_id": job["board_id"], "timeframe": job["timeframe"],
                          "phase": "oos", "done": j + 1, "total": len(top),
                          "current": trial["params"],
                          "trial": {"index": trial["index"],
                                    "status": scored["status"],
                                    "score": trial.get("oos_score")}})
            valid.sort(key=lambda t: -float(t.get("oos_score") or 0))
            job["top"] = valid[:job["holdout"]["top_k"]]
            job["best"] = job["top"][0] if job["top"] else None
            if not job["top"]:
                job["warnings"].append({"code": "NO_OOS_VALID",
                                        "message": "样本外没有满足约束的候选，未选出最优"})
        else:
            job["phase"] = "register"
            job["warnings"].append({"code": "NO_HOLDOUT",
                                    "message": "未做样本外验证（holdout.ratio=0），"
                                               "Top K 仅为样本内候选"})
            registered = []
            for j, trial in enumerate(top):
                if job.get("cancel"):
                    break
                job["current"] = trial["params"]
                self._bc({"type": "optimize_progress", "job_id": job["job_id"],
                          "board_id": job["board_id"], "timeframe": job["timeframe"],
                          "phase": "register", "done": j, "total": len(top),
                          "current": trial["params"]})
                batch = {"id": job["job_id"], "kind": "optimize",
                         "method": job["method"], "index": j, "total": len(top),
                         "params": trial["params"], "phase": "is",
                         "objective": job["objective"],
                         "is_stats": trial.get("is_stats"),
                         "is_score": trial.get("score")}
                try:
                    body = self._execute_run(
                        job["is_ctx"], trial["params"], timeout=job["timeout"],
                        display_name=self._opt_label(job["is_ctx"], trial["params"]),
                        batch=batch)
                except Exception as exc:
                    body = {"error": f"OPTIMIZE_REGISTER_FAILED: {exc}"}
                if body.get("error"):
                    job["errors"].append({"index": trial["index"], "phase": "register",
                                          "params": trial["params"], "error": body["error"]})
                    continue
                res = body.get("result") or {}
                trial["result_id"] = res.get("result_id")
                trial["oos_stats"] = None
                trial["oos_status"] = None
                if trial.get("result_id"):
                    job["registered_result_ids"].append(trial["result_id"])
                    registered.append(trial)
            job["top"] = registered
            job["best"] = registered[0] if registered else None

    def get_optimization(self, job_id):
        job = self._optimize_jobs.get(job_id)
        if not job:
            return {"error": f"OPTIMIZE_JOB_NOT_FOUND: {job_id}"}
        elapsed = job.get("elapsed_ms")
        if elapsed is None and job.get("created_at"):
            elapsed = int((time.time() - float(job["created_at"])) * 1000)
        return {
            "job_id": job["job_id"], "status": job["status"], "phase": job["phase"],
            "board_id": job["board_id"], "timeframe": job["timeframe"],
            "script": job["script"], "method": job["method"],
            "objective": job["objective"], "constraints": job["constraints"],
            "budget": job["budget"], "holdout": job["holdout"], "seed": job["seed"],
            "space": job["space"], "space_size": job.get("space_size"),
            "total": job["total"], "done": job["done"], "oos_done": job.get("oos_done"),
            "current": job.get("current"), "trials": job["trials"],
            "top": job.get("top") or [], "best": job.get("best"),
            "warnings": job["warnings"], "errors": job["errors"],
            "registered_result_ids": job["registered_result_ids"],
            "space_exhausted": bool(job.get("space_exhausted")),
            "cancelled": job["status"] == "cancelled",
            "created_at": job["created_at"], "finished_at": job["finished_at"],
            "elapsed_ms": elapsed,
        }

    def cancel_optimization(self, job_id):
        job = self._optimize_jobs.get(job_id)
        if not job:
            return {"error": f"OPTIMIZE_JOB_NOT_FOUND: {job_id}"}
        if job["status"] != "running":
            return {"status": job["status"], "noop": True}
        job["cancel"] = True
        return {"status": "ok", "cancelling": True, "done": job["done"],
                "total": job["total"], "phase": job["phase"]}

    # ============ 划线 drawings（0.5.2：每板一份，showOn 管跨周期） ============
    def add_drawing(self, board_id, timeframe, drawing):
        result = self.state.add_drawing(board_id, drawing, timeframe)
        if not result.get("error"):
            self._bc({"type": "drawing_add", "board_id": board_id, "drawing": result["drawing"]})
        return result

    def delete_drawing(self, board_id, drawing_id):
        result = self.state.delete_drawing(board_id, drawing_id)
        if not result.get("error"):
            self._bc({"type": "drawing_remove", "board_id": board_id, "id": drawing_id})
        return result

    def delete_drawings(self, board_id, ids):
        result = self.state.delete_drawings(board_id, ids)
        if not result.get("error") and result.get("deleted"):
            self._bc({"type": "drawings_remove", "board_id": board_id,
                      "ids": result["deleted"]})
        return result

    def update_drawing(self, board_id, drawing_id, patch):
        result = self.state.update_drawing(board_id, drawing_id, patch)
        if not result.get("error"):
            self._bc({"type": "drawing_update", "board_id": board_id, "drawing": result["drawing"]})
        return result

    # ---- 画线锚点解析：语义锚点（bars_ago + price 角色）→ 绝对 {time, price} ----
    _PRICE_ROLES = ("open", "high", "low", "close")

    def resolve_drawing_anchors(self, board_id, timeframe, anchors):
        """两种锚点写法：
        · 绝对：{"time": <ms>, "price": <num>}（time/price 缺一由 K 线补）
        · 语义：{"bars_ago": N, "price": "high"|"low"|"close"|"open"}（0=最新一根）
        单锚点类型（hline/vline…）可只给 price 或 time，另一维自动补齐。
        返回 (resolved, error)。"""
        tf = timeframe or self.state.get_default_timeframe(board_id)
        bars = self.state.get_ohlcv(board_id, tf) or []
        by_ts = {int(b["timestamp"]): b for b in bars} if bars else {}
        out = []
        for i, a in enumerate(anchors or []):
            if not isinstance(a, dict):
                return None, f"BAD_ANCHOR[{i}]: 需为对象 {{time,price}} 或 {{bars_ago,price}}"
            time = a.get("time")
            price = a.get("price")
            ago = a.get("bars_ago")
            bar = None
            if ago is not None:
                try:
                    ago = int(ago)
                except (TypeError, ValueError):
                    return None, f"BAD_ANCHOR[{i}]: bars_ago 需为整数"
                idx = len(bars) - 1 - ago
                if idx < 0 or idx >= len(bars):
                    return None, f"ANCHOR_OUT_OF_RANGE[{i}]: bars_ago={ago}，当前周期仅 {len(bars)} 根"
                bar = bars[idx]
            elif time is not None:
                try:
                    bar = by_ts.get(int(time))
                except (TypeError, ValueError):
                    return None, f"BAD_ANCHOR[{i}]: time 需为毫秒时间戳"
            elif bars:
                bar = bars[-1]
            if isinstance(price, str):
                role = price.strip().lower()
                if role not in self._PRICE_ROLES:
                    return None, (f"BAD_ANCHOR[{i}]: price 角色需为 {'/'.join(self._PRICE_ROLES)}，"
                                  f"或给数值")
                if not bar:
                    return None, f"ANCHOR_NO_BAR[{i}]: 用价格角色时需要该周期的 K 线"
                price = bar.get(role)
            if time is None:
                if bar:
                    time = bar.get("timestamp")
                elif ago is None and price is not None and not isinstance(a.get("price"), str):
                    # 单锚点水平线在无 K 线的周期也能落：时间取当前（hline 只用 price）
                    import time as _t
                    time = int(_t.time() * 1000)
                else:
                    return None, f"ANCHOR_NO_BAR[{i}]: 该周期无 K 线，请改给绝对 time"
            if price is None:
                price = bar.get("close") if bar else 0
            out.append({"time": int(time), "price": float(price)})
        return out, ""

    def add_drawings(self, board_id, timeframe, drawings):
        items = self.state.add_drawings(board_id, drawings, timeframe)
        if items:
            self._bc({"type": "drawings_add", "board_id": board_id, "drawings": items})
        return {"status": "ok", "count": len(items), "drawings": items}

    def list_drawings(self, board_id, timeframe=None):
        return {"drawings": self.state.list_drawings(board_id, timeframe)}

    # ============ 区间只读（默认当前 view，秒→毫秒自适应） ============
    def _resolve_range(self, board_id, timeframe, start, end):
        """返回 (ohlcv, i0, i1)；不传 start/end 默认当前 view 窗口。"""
        ohlcv = self.state.get_ohlcv(board_id, timeframe)
        if not ohlcv:
            return None, 0, -1
        start = _to_ms(start)
        end = _to_ms(end)
        n = len(ohlcv)
        if start is None and end is None:
            view = self.current_view
            if view and view.get("board_id") == board_id and view.get("timeframe") == timeframe \
                    and view.get("from_time") and view.get("to_time"):
                start, end = view["from_time"], view["to_time"]
        i0, i1 = 0, n - 1
        if start is not None:
            i0 = next((i for i, b in enumerate(ohlcv) if b["timestamp"] >= start), 0)
        if end is not None:
            i1 = next((i for i in range(n - 1, -1, -1) if ohlcv[i]["timestamp"] <= end), n - 1)
        return ohlcv, i0, i1

    def get_kline(self, board_id, timeframe, start=None, end=None, until=None, limit=None):
        """纯 K 线（含成交量）区间切片；不传范围=当前 view。
        until/limit（P1 修复）：计数型头部窗口——timestamp<until 的 bar 取尾 limit 根；
        与日历无关（交易日缺口源亦精确），供前端 history loadRange 头部取数。"""
        if until is not None:
            until = int(until)
            until = until * 1000 if until < 1e11 else until
            limit = int(limit) if limit else None
            board = self.state.get_board(board_id)
            tf_state = board.get_tf(timeframe) if board else None
            if not tf_state:
                return {"error": "No data"}
            bars = [b for b in (self.state.get_ohlcv(board_id, timeframe) or []) if b["timestamp"] < until]
            if limit:
                bars = bars[-int(limit):]
            # 空窗=正常 genesis 探测（非错误）：200 + 空集，避免客户端 console 噪声
            return {
                "board_id": board_id, "timeframe": timeframe, "symbol": tf_state.symbol,
                "range": {"from": bars[0]["timestamp"] if bars else None,
                          "to": bars[-1]["timestamp"] if bars else None},
                "ohlcv": bars,
            }
        ohlcv, i0, i1 = self._resolve_range(board_id, timeframe, start, end)
        if not ohlcv:
            return {"error": "No data"}
        sliced = ohlcv[i0:i1 + 1]
        tf_state = self.state.get_board(board_id).get_tf(timeframe)
        return {
            "board_id": board_id, "timeframe": timeframe, "symbol": tf_state.symbol,
            "range": {"from": sliced[0]["timestamp"] if sliced else None,
                      "to": sliced[-1]["timestamp"] if sliced else None},
            "ohlcv": sliced,
        }

    def get_indicators(self, board_id, timeframe, start=None, end=None, instances=None):
        """指标值区间切片（省 token）；instances= 按 inst_id 过滤。
        P1：recipe 缓存带 times → 按时间范围（bisect）切片，修正 store>max_window 时
        feed 尾窗与 store 索引错位（旧 i0:i1 直切在长板上偏移）；同时回带 times，
        AI 拿到 (ts,value) 对，无需靠索引猜对齐。blob（无 times）回退 store 索引切片。"""
        ohlcv, i0, i1 = self._resolve_range(board_id, timeframe, start, end)
        t0 = ohlcv[i0]["timestamp"] if ohlcv and 0 <= i0 < len(ohlcv) else None
        t1 = ohlcv[i1]["timestamp"] if ohlcv and 0 <= i1 < len(ohlcv) else None
        want = set(instances) if instances else None
        out = {}
        for inst in self.state.tf_instances(board_id, timeframe):
            if want and inst["inst_id"] not in want:
                continue
            c = self.state.get_cache(board_id, timeframe, inst["inst_id"]) or {}
            entry = {"inst_id": inst["inst_id"], "kind": inst["kind"],
                     "display_name": inst.get("display_name") or inst.get("auto_label") or inst["inst_id"],
                     "subplot": inst["target"], "params": inst["params"],
                     "scope": inst["scope"], "script": inst["script"]}
            ctimes = c.get("times")
            if ctimes and t0 is not None:
                lo = bisect_left(ctimes, t0)
                hi = bisect_right(ctimes, t1) if t1 is not None else len(ctimes)
            else:
                lo, hi = i0, i1 + 1   # 无 times（blob/legacy）→ store 索引切片（旧行为）
            if c.get("values") is not None:
                entry["values"] = c["values"][lo:hi]
            if ctimes:
                entry["times"] = ctimes[lo:hi]
            if c.get("lines"):
                entry["lines"] = [{**ln, "values": (ln.get("values") or [])[lo:hi]}
                                  for ln in c["lines"]]
            if c.get("markers"):
                entry["markers"] = c["markers"]
            if c.get("levels"):
                entry["levels"] = c["levels"]
            if c.get("polylines"):
                entry["polylines"] = c["polylines"]
            out[inst["inst_id"]] = entry
        return {"board_id": board_id, "timeframe": timeframe,
                "range": {"from": t0, "to": t1},
                "indicators": out}

    def get_overview(self, board_id, timeframe):
        """轻量结构总览：只回结构与计数，不回 K 线/指标数值数组（省 token）。"""
        board = self.state.get_board(board_id)
        tf_state = board.get_tf(timeframe) if board else None
        if not tf_state:
            return {"error": "No such board/timeframe"}
        ind_meta = {}
        for inst in self.state.tf_instances(board_id, timeframe):
            ind_meta[inst["inst_id"]] = {
                "kind": inst["kind"], "script": inst["script"],
                "scope": inst["scope"], "target": inst["target"],
                "display_name": inst.get("display_name") or inst.get("auto_label") or inst["inst_id"],
                "params": inst["params"],
                "dynamic": inst["kind"] == "recipe",
                "visible": inst.get("visible", True),   # P2-fix：显隐服务端真源（总览可见）
            }
        view = self.current_view if (self.current_view
                                     and self.current_view.get("board_id") == board_id
                                     and self.current_view.get("timeframe") == timeframe) else None
        return {
            "board_id": board_id, "timeframe": timeframe,
            "symbol": tf_state.symbol, "interval": tf_state.interval,
            "last_updated": tf_state.last_updated, "bars": len(tf_state.ohlcv),
            "view": {"from_time": view.get("from_time"), "to_time": view.get("to_time")} if view else None,
            "source_lock": board.source_lock, "locked": board.locked,
            "kline_source": self.datasource.get(board_id, timeframe),
            "indicators": ind_meta,
            "subplots": [s.get("name") for s in tf_state.subplots.values()],
            "markers_count": len(tf_state.markers),
            "drawings_count": len(board.drawings),
        }

    def set_view_range(self, board_id, timeframe, from_time, to_time):
        """让前端聚焦到指定时间窗口（AI 主动把画面拉到某段时间，如回测亏损区间）。
        写入 current_view 并广播 view_set；前端仅在当前显示的板/周期上应用。"""
        board = self.state.get_board(board_id)
        tf_state = board.get_tf(timeframe) if board else None
        if not tf_state:
            return {"error": "No such board/timeframe"}
        from_time = _to_ms(from_time)
        to_time = _to_ms(to_time)
        if from_time is None or to_time is None or from_time >= to_time:
            return {"error": "Invalid range: need from < to"}
        self.current_view = {"board_id": board_id, "timeframe": timeframe,
                             "from_time": from_time, "to_time": to_time,
                             "updated_at": datetime.now().isoformat()}
        self._bc({"type": "view_set", "board_id": board_id, "timeframe": timeframe,
                  "from_time": from_time, "to_time": to_time})
        return {"status": "ok", "board_id": board_id, "timeframe": timeframe,
                "from_time": from_time, "to_time": to_time}

    def create_subplot(self, board_id, timeframe, name, height=150, title=None):
        result = self.state.create_subplot(board_id, timeframe, name, height, title)
        if not result.get("error"):
            self._bc({"type": "subplot_create", "board_id": board_id, "timeframe": timeframe,
                      "name": name, "height": height, "title": title})
        return result

    def update_subplot(self, board_id, timeframe, name, height=None, title=None):
        result = self.state.update_subplot(board_id, timeframe, name, height, title)
        if not result.get("error"):
            self._bc({"type": "subplot_update", "board_id": board_id, "timeframe": timeframe,
                      "name": name, "height": result.get("height"), "title": result.get("title")})
        return result

    def delete_subplot(self, board_id, timeframe, name):
        result = self.state.delete_subplot(board_id, timeframe, name)
        if not result.get("error"):
            self._bc({"type": "subplot_remove", "board_id": board_id, "timeframe": timeframe,
                      "name": name})
        return result

    def list_subplots(self, board_id, timeframe):
        return {"subplots": self.state.list_subplots(board_id, timeframe)}

    # ============ 数据源 ============
    def set_kline_source(self, board_id, tf, script, params=None, poll_s=None, fetch_timeout=None):
        """声明式配置 K 线来源（幂等，PUT 语义）。script 为 id（kind/name）。
        - 空板首配 = 锁定（source_lock 就位）；已锁板全槽全等校验，违则 SOURCE_LOCKED+suggestion
        - IDENTITY 键之外的 params = 操作参数，自由改（改即重拉）；仅 poll_s 变 = 不碰数据
        - 指标随附打包参已废除——指标唯一入口 add_indicator"""
        params = params or {}
        poll_s = poll_s or 5   # v0.4.4 bug10：入口归一，保 noop 恒等比较语义（None vs 5 曾致 noop 变 poll_only）
        board = self.state.get_board(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        if self.script_engine.resolve(script) is None:
            from .script_engine import id_error
            return {"error": f"SCRIPT_NOT_FOUND: {script}" if "/" in str(script)
                    else id_error(script)}
        if board.source_lock is None:
            lock_err = self._lock_board(board_id, script, params)
            if lock_err:
                return lock_err
        else:
            lock = board.source_lock
            if script != lock["script"]:
                return self._locked_err(board, script, params)
            for k, v in (lock.get("identity") or {}).items():
                if params.get(k) != v:
                    return self._locked_err(board, script, params)

        # §2.2 系统注入：在线板槽位 params 恒带 interval=槽名（面板名=周期）
        params = {**params, "interval": tf}
        key = self.datasource._key(board_id, tf)
        cur = self.datasource.configs.get(key)
        # 幂等：配置完全相同 = no-op
        if cur and cur["script"] == script and cur["params"] == params \
                and cur.get("poll_s") == poll_s:
            return {"status": "ok", "noop": True}
        # 仅 poll_s 变 = 不碰数据（轮询循环动态读 poll_s）
        if cur and cur["script"] == script and cur["params"] == params:
            self.datasource.stop_sync(board_id, tf)
            self.datasource.set_config(board_id, tf, script, params, poll_s)
            self.datasource.start(board_id, tf, script, params, poll_s)  # bug10：无条件启线程
            self._bc({"type": "kline_source_set", "board_id": board_id, "timeframe": tf,
                      "script": script, "params": params, "poll_s": poll_s})
            return {"status": "ok", "poll_only": True}

        # script/params 变 = 停旧源、重拉一次
        self.datasource.stop_sync(board_id, tf)
        if fetch_timeout:
            # v0.4.4：同步首拉上限（超时=空K线建板、轮询线程后续填数自愈）——
            # 建板响应永不被烂网/慢源阻塞（曾致 hang 源建板 45s+ 连带搜索全瘫）
            from concurrent.futures import ThreadPoolExecutor
            _ex = ThreadPoolExecutor(max_workers=1)
            _f = _ex.submit(self.script_engine.run_script, script, params)
            try:
                result = _f.result(timeout=fetch_timeout)
            except Exception:
                # v0.4.4 用户裁决：拉不到数据=建板失败+原因，不建空板
                result = {"error": f"SOURCE_FETCH_TIMEOUT: 首拉超 {fetch_timeout}s 无数据"
                          f"（源网络限流窗/不可达）——建板失败，请稍后重试"}
            _ex.shutdown(wait=False, cancel_futures=True)
        else:
            result = self.script_engine.run_script(script, params)
        if result.get("error"):
            return result
        data = result.get("data", [])
        self.state.set_ohlcv(board_id, tf, data)
        self.recompute_indicators(board_id, tf)
        self.datasource.set_config(board_id, tf, script, params, poll_s)
        self.datasource.start(board_id, tf, script, params, poll_s)  # bug10：无条件启线程
        # 首拉也是拉：status.last_fetch 语义=最近一次真实取数（去重/新鲜度判定依赖）
        st = self.datasource.status.setdefault(self.datasource._key(board_id, tf), {})
        st["last_fetch"] = datetime.now().isoformat()
        st["last_error"] = None
        self._bc({"type": "kline_source_set", "board_id": board_id, "timeframe": tf,
                  "script": script, "params": params, "poll_s": poll_s})
        self._bc({"type": "ohlcv_update", "board_id": board_id, "timeframe": tf,
                  "data": data, "markers": []})
        return {"status": "ok", "count": len(data)}

    def get_kline_source(self, board_id, tf):
        r = self.datasource.get(board_id, tf)
        cfg = self.datasource.configs.get(self.datasource._key(board_id, tf))
        if isinstance(r, dict) and cfg:
            # 性能①可读面：当前生效轮询间隔（可见=poll_s；非可见=降频档）
            r = {**r, "eff_poll_s": self.datasource.effective_poll_s(cfg)}
        return {"kline_source": r}

    def interval_options(self, board_id):
        """周期"+"按钮数据：仅实时源(声明 INTERVALS)可加；离线板 online=False"""
        board = self.state.get_board(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        current = list(board.intervals)
        lock = board.source_lock
        if not lock:
            return {"online": False, "supported": [], "current": current, "addable": []}
        meta = self.script_engine.metadata(lock["script"])
        supported = (meta or {}).get("intervals") or []
        return {"online": bool(supported), "supported": supported, "current": current,
                "addable": [iv for iv in supported if iv not in current]}

    def save_script(self, id, code):
        """save_script 服务包装：保存即校验 + scripts_changed 广播（刷菜单）"""
        r = self.script_engine.save_script(id, code)
        if r.get("ok"):
            self._bc({"type": "scripts_changed", "id": id})
        return r

    def refresh_timeframe(self, board_id, tf):
        ds = self.datasource.get(board_id, tf)
        if ds and ds.get("script"):
            result = self.script_engine.run_script(ds["script"], ds.get("params", {}))
            if not result.get("error"):
                self.state.set_ohlcv(board_id, tf, result.get("data", []))
        self.recompute_indicators(board_id, tf)
        return {"status": "ok"}

    def backfill(self, board_id, tf, limit=200):
        """向左补更早历史（原 load_history）：读槽配置重放配方 + until=当前最早；
        CAPS.backfill 门控，无徽章返回 0 并注明 NO_BACKFILL"""
        ds = self.datasource.get(board_id, tf)
        if not ds or not ds.get("script"):
            return {"prepended": 0, "error": "No datasource configured"}
        if not self.script_engine.caps(ds["script"]).get("backfill"):
            return {"prepended": 0, "error": f"NO_BACKFILL: {ds['script']} 未声明 CAPS.backfill"}
        ohlcv = self.state.get_ohlcv(board_id, tf)
        if not ohlcv:
            return {"prepended": 0}
        earliest = ohlcv[0]["timestamp"]
        params = dict(ds.get("params", {}))
        params.pop("until", None)  # until 是调用参数，走签名不走 params
        params["limit"] = limit
        result = self.script_engine.run_script(ds["script"], params, until=earliest)
        if result.get("error"):
            return {"prepended": 0, "error": result["error"]}
        older = [b for b in result.get("data", []) if b["timestamp"] < earliest]
        if not older:
            return {"prepended": 0}
        older.sort(key=lambda b: b["timestamp"])
        # P1 修复：严格按 limit 契约截断（脚本按日历 span 会超取）；
        # 保证 prepended == 客户端 until 窗容量 ⇒ 镜像头与 Vela 头恒对齐（左滑阈值依赖该不变量）
        if limit and len(older) > limit:
            older = older[-int(limit):]
        new_ohlcv = older + ohlcv
        markers = self.state.get_timeframe_state(board_id, tf).get("markers", [])
        self.state.set_ohlcv(board_id, tf, new_ohlcv, markers)
        self.state.shift_blob_caches(board_id, tf, len(older))  # blob 头部补 None 保索引对齐
        self.bc_ohlcv_delta(board_id, tf, ohlcv, new_ohlcv, markers=markers)
        self.recompute_indicators(board_id, tf)
        return {"prepended": len(older), "total": len(new_ohlcv)}

    # ============ 状态 ============
    def get_state(self, board_id, timeframe):
        return self.state.get_timeframe_state(board_id, timeframe)

    def get_full_state(self, board_id):
        return self.state.get_full_state(board_id)

    # ============ 内部 ============
    def _all_timeframes(self, board_id):
        board = self.state.get_board(board_id)
        return list(board.timeframes.keys()) if board else []

    def _ensure_subplot(self, board_id, tf, subplot):
        if not subplot:
            return
        board = self.state.get_board(board_id)
        tf_state = board.get_tf(tf) if board else None
        if tf_state and subplot not in tf_state.subplots:
            # v0.4.3 bug1 二连修：走 service 面（带 subplot_create 广播），
            # 原直调 state 致前端不知新副图→容器不渲染（指标线无处可去）
            self.create_subplot(board_id, tf, subplot, 150, subplot)

    # ============ 快照（v0.4.1 收编自 mcp_server；NO_BROWSER 门） ============
    async def take_snapshot(self, board_id=None, timeframe=None, wait=1.5, allow_stale=False):
        """触发前端截图并返回图片+路径；无浏览器在线报 NO_BROWSER（默认不回退磁盘旧图）。
        allow_stale=True（v0.4.2 B）：无浏览器时显式接受最近磁盘快照，
        返回体带 stale:true + 文件时间戳，调用方自行判断可用性。"""
        import asyncio
        if not self._ws_active():
            if allow_stale:
                r = self.get_snapshot(board_id, timeframe)
                if not r.get("error"):
                    import os, datetime as _dt
                    r["stale"] = True
                    r["stale_since"] = _dt.datetime.fromtimestamp(
                        os.path.getmtime(r["path"])).isoformat()
                return r
            return {"error": "NO_BROWSER: 无浏览器连接 /ws，快照需在线前端；"
                             "请先打开 Web UI（或确认目标标签页存活）再截图；"
                             "接受旧图可传 allow_stale=true（返回带 stale:true 标记）"}
        self.notify({"type": "snapshot_request", "board_id": board_id, "timeframe": timeframe})
        await asyncio.sleep(wait)
        return self.get_snapshot(board_id, timeframe)

    def get_snapshot(self, board_id=None, timeframe=None):
        """读取最新快照（图片 base64+路径）"""
        import base64 as _b64
        d = self.snapshot_dir
        board = board_id or self.state.current_board_id or "board"
        path = d / f"{board}_{timeframe or 'latest'}.png"
        if not path.exists():
            files = sorted(d.glob("*.png"))
            if not files:
                return {"error": "NO_SNAPSHOT: 尚无快照文件"}
            path = files[-1]
        return {"path": str(path), "size": path.stat().st_size,
                "image_b64": _b64.b64encode(path.read_bytes()).decode()}

    def _ws_active(self):
        return False

    def _bc(self, message):
        try:
            self.notify(message)
        except Exception as e:
            logger.debug(f"notify error: {e}")
