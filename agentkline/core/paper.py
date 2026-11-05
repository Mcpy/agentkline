"""模拟盘（paper）会话 / 账本 / bar 执行器（v0.7.1）。

口径与回测相同：P 收盘算 target，下一根 B 开盘成交，B 的 high/low 查保护，
B 收盘记权益；复用 `MatchingEngine`，不引入“当前价成交”。

0.7.1 只做一个会话一个标的/周期/策略；线程模型是每会话一个 worker，
bar 到达只唤醒 worker，不阻塞数据源轮询线程。
"""
from __future__ import annotations

import copy
import hashlib
import logging
import math
import threading
import time
import uuid
from bisect import bisect_left

from agentkline_engine.matching import MatchingEngine

from ..backtest import runner as engine_runner
from .results import bars_per_year, next_result_id, normalize_result, summarize

logger = logging.getLogger("agentkline.paper")

DEFAULT_WINDOW_BARS = 0          # 0=自动；显式配置才走手动窗口
AUTO_WINDOW_MIN = 500           # 自动窗口下限
AUTO_WINDOW_TAIL = 100         # 在 WARMUP 之外多留的 bar
MIN_WINDOW_BARS = 100
MAX_WINDOW_BARS = 50000
DEFAULT_MAX_CATCHUP_BARS = 500
MAX_CATCHUP_BARS = 5000
DEFAULT_SETTLE_MS = 15_000   # bar 收盘后再等 15s，避开交易所最后一跳修订

_ACTIVE_STATUSES = ("created", "running", "paused", "paused_gap", "error")
_TERMINAL = ("stopped",)
_TF_MS = {"m": 60_000, "h": 3_600_000, "d": 86_400_000,
          "w": 7 * 86_400_000, "M": 30 * 86_400_000}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _tf_ms(tf: str):
    tf = (tf or "").strip()
    try:
        n = int(tf[:-1])
        unit = tf[-1]
    except (ValueError, IndexError):
        return None
    ms = _TF_MS.get(unit)
    return n * ms if ms else None


def _is_closed(bar: dict, tf: str, now_ms: int, settle_ms: int = 0) -> bool:
    """按 bar 开盘时间 + 周期 + 收盘静默期判断是否已收盘。"""
    span = _tf_ms(tf)
    if not span:
        return True
    try:
        return int(bar["timestamp"]) + span + max(0, int(settle_ms)) <= int(now_ms)
    except (KeyError, TypeError, ValueError):
        return False


def _latest_closed(bars: list[dict], tf: str, now_ms: int, settle_ms: int = 0):
    for bar in reversed(bars or []):
        if _is_closed(bar, tf, now_ms, settle_ms):
            return bar
    return None


def resolve_window_bars(warmup: int = 0, requested=None) -> dict:
    """解析 paper 策略窗口。

    默认自动：max(500, WARMUP+100)。显式传正数才走手动覆盖；
    手动小于 MIN_WINDOW_BARS 或 WARMUP+1 时向上夹取并标记 adjusted。
    """
    try:
        warm = max(0, int(warmup or 0))
    except (TypeError, ValueError):
        warm = 0
    raw = requested
    auto = raw is None or str(raw).strip().lower() in ("", "auto", "0")
    adjusted = False
    if auto:
        mode = "auto"
        resolved = max(AUTO_WINDOW_MIN, warm + AUTO_WINDOW_TAIL)
        raw_out = None
    else:
        mode = "manual"
        try:
            resolved = int(raw)
            raw_out = resolved
        except (TypeError, ValueError):
            raise ValueError("PAPER_WINDOW_INVALID: window_bars 需要整数或 0(auto)")
        floor = max(MIN_WINDOW_BARS, warm + 1)
        if resolved < floor:
            resolved = floor
            adjusted = True
    if resolved > MAX_WINDOW_BARS:
        resolved = MAX_WINDOW_BARS
        adjusted = True
    return {"mode": mode, "requested": raw_out, "resolved": int(resolved),
            "warmup": warm, "adjusted": adjusted}


class PaperManager:
    """paper 会话管理器；由 AgentKlineService 持有。"""

    def __init__(self, service):
        self.service = service
        self.store = getattr(service, "store", None)
        limits = getattr(service, "limits", {}) or {}
        cfg_window = limits.get("paper_window_bars", DEFAULT_WINDOW_BARS)
        if cfg_window in (None, "", 0, "0", "auto"):
            self.window_bars = 0          # 自动
        else:
            self.window_bars = self._clamp_int(cfg_window, MIN_WINDOW_BARS, MAX_WINDOW_BARS)
        self.max_catchup = self._clamp_int(
            limits.get("paper_max_catchup_bars", DEFAULT_MAX_CATCHUP_BARS),
            10, MAX_CATCHUP_BARS)
        self.settle_ms = self._clamp_int(
            limits.get("paper_settle_ms", DEFAULT_SETTLE_MS), 0, 300_000)
        self.sessions: dict[str, dict] = {}
        self._wake: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._processing: set[str] = set()
        self._reconciling: set[str] = set()
        self._lock = threading.RLock()
        self._load()

    @staticmethod
    def _clamp_int(v, lo, hi) -> int:
        try:
            n = int(v)
        except (TypeError, ValueError):
            n = lo
        return max(lo, min(n, hi))

    # ---------------------------- 启动恢复 ----------------------------
    def _load(self) -> None:
        if not self.store:
            return
        try:
            rows = self.store.list_paper_sessions(limit=500)
        except Exception:
            logger.exception("paper 会话恢复失败")
            return
        for s in rows:
            self._ensure_window_meta(s)
            self.sessions[s["session_id"]] = s
            if s.get("status") == "running":
                self._ensure_worker(s["session_id"])
        if rows:
            logger.info("paper 恢复: %d 个会话（running=%d）", len(rows),
                        sum(1 for s in rows if s.get("status") == "running"))

    def _ensure_window_meta(self, s: dict) -> None:
        """兼容 0.7.0 会话：补齐窗口元数据，不改已冻结的 window_bars。"""
        st = s.get("state")
        if not isinstance(st, dict):
            st = {}
            s["state"] = st
        if "window_resolved" in st:
            return
        resolved = int(s.get("window_bars") or self.window_bars or AUTO_WINDOW_MIN)
        if resolved <= 0:
            resolved = AUTO_WINDOW_MIN
        st["window_mode"] = "manual"
        st["window_requested"] = resolved
        st["window_resolved"] = resolved
        st["window_warmup"] = int(st.get("warmup") or 0)
        st["window_actual"] = None
        st["window_short"] = False
        st["window_truncated"] = bool(st.get("window_truncated"))

    def _ensure_worker(self, session_id: str) -> None:
        with self._lock:
            th = self._threads.get(session_id)
            if th and th.is_alive():
                return
            ev = self._wake.setdefault(session_id, threading.Event())
            th = threading.Thread(target=self._worker, args=(session_id, ev),
                                  daemon=True, name=f"ak-paper-{session_id}")
            self._threads[session_id] = th
            th.start()

    # ---------------------------- 公共查询 ----------------------------
    def list(self, board_id: str = None, status: str = None, limit: int = 100) -> dict:
        if self.store:
            rows = self.store.list_paper_sessions(board_id=board_id, status=status,
                                                  limit=limit)
            # 以内存态为准（可能有刚写入还没回读的字段）
            out = [self._public(self.sessions.get(r["session_id"]) or r)
                   for r in rows]
        else:
            out = [self._public(s) for s in self.sessions.values()
                   if (not board_id or s["board_id"] == board_id)
                   and (not status or s["status"] == status)]
            out.sort(key=lambda x: x.get("created_at") or 0, reverse=True)
            out = out[:max(1, min(int(limit or 100), 500))]
        return {"sessions": out, "count": len(out)}

    def get(self, session_id: str, include_events: bool = False) -> dict:
        s = self._get(session_id)
        if not s:
            return {"error": "PAPER_NOT_FOUND: 会话不存在", "code": "PAPER_NOT_FOUND"}
        out = self._public(s, include_details=True)
        if include_events and self.store:
            # 取最后 30 条（不是最老 30 条）；seq 从 1 开始
            total = int(self.store.load_paper_events(session_id, 0, 1).get("total") or 0)
            ev = self.store.load_paper_events(session_id, max(0, total - 30), 30)
            out["events"] = list(reversed(ev.get("items") or []))
        return out

    def events(self, session_id: str, after_seq: int = 0, limit: int = 200) -> dict:
        if not self._get(session_id):
            return {"error": "PAPER_NOT_FOUND: 会话不存在", "code": "PAPER_NOT_FOUND"}
        if not self.store:
            return {"session_id": session_id, "items": [], "total": 0,
                    "returned": 0, "next_after_seq": after_seq, "truncated": False}
        return self.store.load_paper_events(session_id, after_seq, limit)

    def equity(self, session_id: str, offset: int = 0, limit: int = 0) -> dict:
        if not self._get(session_id):
            return {"error": "PAPER_NOT_FOUND: 会话不存在", "code": "PAPER_NOT_FOUND"}
        if not self.store:
            return {"session_id": session_id, "points": [], "total": 0,
                    "offset": offset, "returned": 0, "truncated": False,
                    "next_offset": None}
        return self.store.load_paper_equity(session_id, offset, limit)

    # ---------------------------- 创建 / 控制 ----------------------------
    def create(self, board_id: str, timeframe: str = None, script: str = None,
               params: dict = None, direction: str = "long_only",
               initial_cash: float = 10000.0, fee_bps: float = 5.0,
               slippage_bps: float = 5.0, protection: dict = None,
               window_bars: int = None, preset_id: str = None,
               source: str = None) -> dict:
        board = self.service.state.get_board(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        tf = timeframe or board.current_timeframe
        if not (board.get_tf(tf) and board.get_tf(tf).ohlcv):
            return {"error": "NO_BARS: 该周期还没有已载入的 K 线，先等行情加载完再开模拟盘"}
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

        preset = None
        if preset_id and self.store:
            preset = self.store.get_preset(preset_id)
            if not preset:
                return {"error": f"PRESET_NOT_FOUND: {preset_id}"}
            script = script or preset.get("script")
            params = {**(preset.get("params") or {}), **(params or {})}

        src, err = self.service._strategy_source(script, source)
        if err:
            return {"error": err}
        try:
            from agentkline_engine.loader import describe_source
            from agentkline_engine.drivers.signal import merge_protection
            info = describe_source(src)
        except Exception:
            return {"error": "ENGINE_UNAVAILABLE: 引擎框架未安装"}
        if info.get("errors"):
            return {"error": f"STRATEGY_INVALID: {info['errors'][0].get('message')}"}
        merged_params = {**(info.get("params") or {}), **(params or {})}
        try:
            merged_prot = merge_protection(info.get("protection") or {}, protection)
        except Exception as exc:  # AKError
            return {"error": f"{getattr(exc, 'code', 'PROTECTION_INVALID')}: {exc}"}
        # 显式传 0/None 都走自动；只有正数才是手动窗口
        if window_bars is None:
            requested_window = None if not self.window_bars else self.window_bars
        else:
            requested_window = window_bars
        try:
            winfo = resolve_window_bars(info.get("warmup"), requested_window)
        except ValueError as exc:
            return {"error": str(exc), "code": "PAPER_WINDOW_INVALID"}

        with self._lock:
            for s in self.sessions.values():
                if (s["board_id"] == board_id and s["timeframe"] == tf
                        and s["status"] in _ACTIVE_STATUSES):
                    return {"error": "PAPER_SESSION_EXISTS: 该画板+周期已有未结束的模拟盘",
                            "code": "PAPER_SESSION_EXISTS",
                            "session_id": s["session_id"]}

            latest = _latest_closed(board.get_tf(tf).ohlcv, tf, _now_ms(), self.settle_ms)
            if not latest:
                return {"error": "NO_CLOSED_BARS: 还没有已收盘的 K 线，无法确定启动点"}
            cursor = int(latest["timestamp"])
            now = _now_ms()
            sid = "pp_" + uuid.uuid4().hex[:10]
            bars = board.get_tf(tf).ohlcv or []
            cursor_idx = next((i for i, b in enumerate(bars)
                               if int(b["timestamp"]) == cursor), len(bars) - 1)
            winfo["actual"] = min(winfo["resolved"], cursor_idx + 1)
            # “窗口不足”只表示连 WARMUP 都不够；小于请求窗口但大于 WARMUP
            # 仍能按策略契约正常输出，不告警。
            winfo["short"] = winfo["actual"] <= winfo["warmup"]
            winfo["truncated"] = len(bars) > winfo["actual"]
            state = {
                "cash": cash, "pos": 0.0, "avg_price": 0.0, "equity": cash,
                "fills": [], "trades": [], "trade": None,
                "bars_processed": 0, "last_decision": None, "last_fill": None,
                "window_truncated": bool(winfo["truncated"]),
                "window_actual": int(winfo["actual"]),
                "window_short": bool(winfo["short"]),
                "window_mode": winfo["mode"],
                "window_requested": winfo["requested"],
                "window_resolved": winfo["resolved"],
                "window_warmup": winfo["warmup"],
                "window_adjusted": bool(winfo["adjusted"]),
                "warnings_seen": [],
                "warmup": int(info.get("warmup") or 0),
                "strategy_name": (info.get("name") or "").strip(),
            }
            session = {
                "session_id": sid, "board_id": board_id, "timeframe": tf,
                "script": script or "strategy/inline", "source": src,
                "script_sha256": hashlib.sha256(src.encode("utf-8")).hexdigest(),
                "preset_id": preset_id, "params": merged_params,
                "direction": direction, "initial_cash": cash,
                "fee_bps": fee, "slippage_bps": slip, "protection": merged_prot,
                "window_bars": int(winfo["resolved"]),
                "status": "created", "cursor_ts": cursor, "last_seen_ts": cursor,
                "state": state, "result_id": None, "last_error": None,
                "created_at": now, "started_at": None, "stopped_at": None,
                "strategy_name": (info.get("name") or "").strip(),
            }
            if self.store:
                self.store.create_paper_session(session)
            self.sessions[sid] = session
        return self.get(sid)

    def start(self, session_id: str) -> dict:
        return self._activate(session_id, first=True)

    def resume(self, session_id: str) -> dict:
        return self._activate(session_id, first=False)

    def _activate(self, session_id: str, first: bool) -> dict:
        with self._lock:
            s = self._get(session_id)
            if not s:
                return {"error": "PAPER_NOT_FOUND: 会话不存在", "code": "PAPER_NOT_FOUND"}
            if s["status"] == "running":
                return self._public(s)
            if s["status"] == "stopped":
                return {"error": "PAPER_STOPPED: 已停止的会话不能重新启动",
                        "code": "PAPER_STOPPED"}
            bars = self.service.state.get_ohlcv(s["board_id"], s["timeframe"]) or []
            latest = _latest_closed(bars, s["timeframe"], _now_ms(), self.settle_ms)
            if not latest:
                return {"error": "NO_CLOSED_BARS: 还没有已收盘的 K 线，无法启动"}
            warmup = int((s.get("state") or {}).get("warmup") or 0)
            if len(bars) <= warmup and self.store:
                # 数据不足时先自动补历史；补完仍不够才拒绝启动，不把问题丢给用户。
                try:
                    self.service._ensure_history(
                        s["board_id"], s["timeframe"], int(latest["timestamp"]),
                        want=0, warmup=warmup + 1, budget_s=10.0)
                except Exception:
                    logger.debug("paper 启动补历史失败", exc_info=True)
                bars = self.service.state.get_ohlcv(s["board_id"], s["timeframe"]) or []
                latest = _latest_closed(bars, s["timeframe"], _now_ms(), self.settle_ms)
                if not latest:
                    return {"error": "NO_CLOSED_BARS: 补历史后仍没有已收盘的 K 线",
                            "code": "PAPER_NO_CLOSED_BARS"}
            if len(bars) <= warmup:
                return {"error": (f"PAPER_WARMUP_INSUFFICIENT: 策略需要超过 {warmup} 根，"
                                  f"当前只有 {len(bars)} 根；已尝试自动补历史仍不足"),
                        "code": "PAPER_WARMUP_INSUFFICIENT"}
            latest_ts = int(latest["timestamp"])
            cursor = s.get("cursor_ts") or latest_ts
            skipped = sum(1 for b in bars
                          if int(b["timestamp"]) > int(cursor)
                          and _is_closed(b, s["timeframe"], _now_ms(), self.settle_ms))
            now = _now_ms()
            events = []
            winfo = self._window_info({**s, "cursor_ts": latest_ts}, bars)
            if first:
                events.append({"ts": now, "bar_ts": latest_ts, "kind": "started",
                               "payload": {"cursor_ts": latest_ts,
                                           "last_seen_ts": latest_ts,
                                           "window": winfo}})
                s["started_at"] = s.get("started_at") or now
            else:
                events.append({"ts": now, "bar_ts": latest_ts, "kind": "resumed",
                               "payload": {"skipped_bars": skipped,
                                           "from_cursor_ts": cursor,
                                           "to_latest_ts": latest_ts,
                                           "mode": "skip"}})
                if skipped:
                    events.append({"ts": now, "bar_ts": latest_ts, "kind": "warning",
                                   "payload": {"code": "PAPER_RESUME_SKIP",
                                               "message": f"恢复跳过 {skipped} 根暂停期 bar"}})
            # 统一从最新已收盘 bar 继续：暂停/断线期间不补跑，避免一次性补几百根
            s["cursor_ts"] = latest_ts
            s["last_seen_ts"] = latest_ts
            s["status"] = "running"
            s["last_error"] = None
            s["state"]["window_actual"] = winfo.get("actual")
            s["state"]["window_short"] = bool(winfo.get("short"))
            s["state"]["window_truncated"] = bool(winfo.get("truncated"))
            s["state"]["equity"] = self._matcher(s).equity(float(latest["close"]))
            init_points = []
            if first and self.store:
                # 0.7.1：启动时把“初始资金”写成真实权益点（P0），曲线从
                # 模拟盘启动那一刻的 10000 开始；下一根 B 收盘才计入首笔成交成本。
                had_eq = int(self.store.load_paper_equity(session_id, 0, 1).get("total") or 0)
                if not had_eq:
                    init_eq = float(s["state"].get("equity") or s.get("initial_cash") or 0.0)
                    init_points = [[latest_ts, init_eq]]
                    events.append({
                        "ts": now, "bar_ts": latest_ts, "kind": "equity",
                        "payload": {"equity": init_eq,
                                    "cash": float(s["state"].get("cash") or init_eq),
                                    "pos": float(s["state"].get("pos") or 0.0),
                                    "price": float(latest["close"]),
                                    "initial": True}})
            if self.store:
                self.store.update_paper_session(
                    session_id, started_at=s.get("started_at"))
                self.store.save_paper_step(
                    session_id, state=s["state"], events=events,
                    equity_points=init_points or None,
                    cursor_ts=latest_ts, last_seen_ts=latest_ts, status="running")
            self._ensure_worker(session_id)
            self._wake.setdefault(session_id, threading.Event()).set()
        self._broadcast_events(s, events)
        self._bc("paper_started" if first else "paper_resumed", s)
        return self._public(s)

    def pause(self, session_id: str) -> dict:
        with self._lock:
            s = self._get(session_id)
            if not s:
                return {"error": "PAPER_NOT_FOUND: 会话不存在", "code": "PAPER_NOT_FOUND"}
            if s["status"] == "paused":
                return self._public(s)
            if s["status"] != "running":
                return {"error": f"PAPER_STATE: 当前状态 {s['status']} 不能暂停",
                        "code": "PAPER_STATE"}
            now = _now_ms()
            ev = {"ts": now, "bar_ts": s.get("last_seen_ts"), "kind": "paused",
                  "payload": {"cursor_ts": s.get("cursor_ts")}}
            s["status"] = "paused"
            if self.store:
                self.store.save_paper_step(session_id, state=s["state"], events=[ev],
                                           status="paused")
            self._wake.setdefault(session_id, threading.Event()).set()
        self._broadcast_events(s, [ev])
        self._bc("paper_paused", s)
        return self._public(s)

    def stop(self, session_id: str) -> dict:
        with self._lock:
            s = self._get(session_id)
            if not s:
                return {"error": "PAPER_NOT_FOUND: 会话不存在", "code": "PAPER_NOT_FOUND"}
            if s["status"] == "stopped":
                return self._public(s)
            bars = self.service.state.get_ohlcv(s["board_id"], s["timeframe"]) or []
            latest = _latest_closed(bars, s["timeframe"], _now_ms(), self.settle_ms)
            now = _now_ms()
            if latest:
                m = self._matcher(s)
                s["state"].update(m.snapshot())
                s["state"]["equity"] = m.equity(float(latest["close"]))
            ev = {"ts": now, "bar_ts": s.get("last_seen_ts"), "kind": "stopped",
                  "payload": {"equity": s["state"].get("equity"),
                              "cursor_ts": s.get("cursor_ts")}}
            s["status"] = "stopped"
            s["stopped_at"] = now
            if self.store:
                self.store.save_paper_step(session_id, state=s["state"], events=[ev],
                                           status="stopped", stopped_at=now)
            self._wake.setdefault(session_id, threading.Event()).set()
        # 物化结果在锁外做（normalize 只算，不执行策略）
        try:
            rid = self._materialize_result(s)
            if rid:
                s["result_id"] = rid
                if self.store:
                    self.store.update_paper_session(session_id, result_id=rid)
        except Exception:
            logger.exception("paper 结果物化失败: %s", session_id)
        self._broadcast_events(s, [ev])
        self._bc("paper_stopped", s)
        return self._public(s)

    def reconcile(self, session_id: str, timeout: float = 120.0,
                  save_result: bool = False) -> dict:
        """同一会话串行对账；重复点击/多端并发直接返回 BUSY，不重复建结果。"""
        if not self._get(session_id):
            return {"error": "PAPER_NOT_FOUND: 会话不存在", "code": "PAPER_NOT_FOUND"}
        with self._lock:
            if session_id in self._reconciling:
                return {"error": "PAPER_RECONCILE_BUSY: 对账正在进行，请等当前一次结束",
                        "code": "PAPER_RECONCILE_BUSY"}
            self._reconciling.add(session_id)
        try:
            return self._reconcile_impl(session_id, timeout=timeout,
                                        save_result=save_result)
        finally:
            with self._lock:
                self._reconciling.discard(session_id)

    def _reconcile_impl(self, session_id: str, timeout: float = 120.0,
                        save_result: bool = False) -> dict:
        """用同一段 bars/参数/窗口跑区间回测，和 paper 的权益/成交/回合对账。

        口径：从第一条 decision 的 P 到最后一条 equity 的 B；回测在 P 当根
        `start_flat`（paper 起始空仓），末根 `flatten=false`（paper 不强平）。
        """
        s = self._get(session_id)
        if not s:
            return {"error": "PAPER_NOT_FOUND: 会话不存在", "code": "PAPER_NOT_FOUND"}
        if not self.store:
            return {"error": "PAPER_RECONCILE_NO_STORE: 当前没有现场库",
                    "code": "PAPER_RECONCILE_NO_STORE"}
        try:
            events = self._all_events(session_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"PAPER_RECONCILE_EVENTS: 读取事件失败: {exc}",
                    "code": "PAPER_RECONCILE_EVENTS"}
        decisions = [e for e in events if e.get("kind") == "decision"
                     and e.get("bar_ts") is not None]
        eq_events = [e for e in events if e.get("kind") == "equity"
                     and e.get("bar_ts") is not None]
        if not decisions or not eq_events:
            return {"error": "PAPER_RECONCILE_EMPTY: 还没有 decision/equity，先跑一根 bar",
                    "code": "PAPER_RECONCILE_EMPTY"}
        p0 = int(decisions[0]["bar_ts"])
        bn = int(eq_events[-1]["bar_ts"])
        # 历史回补：paper 启动时可能还有更早的 bars，数据源后来只保留了短窗口。
        # 先把 P0 之前补到与窗口同量级，否则回测会在 warmup 处被夹住，误报不一致。
        winfo0 = self._window_info(s)
        # 对账只需要足够覆盖 WARMUP 的历史；不要为了旧会话的 5000 请求
        # 每次都回补 5000 根（网络慢时会卡住，且会拖慢重复点击）。
        backfill_target = max(500, int(winfo0.get("warmup") or 0) + 100)
        try:
            self.service._ensure_history(
                s["board_id"], s["timeframe"], p0,
                want=backfill_target, warmup=backfill_target, budget_s=10.0)
        except Exception:
            logger.debug("paper reconcile 回补历史失败", exc_info=True)
        bars = self.service.state.get_ohlcv(s["board_id"], s["timeframe"]) or []
        ts_list = [int(b["timestamp"]) for b in bars]
        p0_idx = bisect_left(ts_list, p0)
        bn_idx = bisect_left(ts_list, bn)
        missing = []
        if p0_idx >= len(ts_list) or ts_list[p0_idx] != p0:
            missing.append(p0)
        if bn_idx >= len(ts_list) or ts_list[bn_idx] != bn:
            missing.append(bn)
        if missing:
            return {"error": "PAPER_RECONCILE_BARS_MISSING: 当前行情缺 bar: "
                             + ", ".join(str(x) for x in missing),
                    "code": "PAPER_RECONCILE_BARS_MISSING", "missing": missing}
        winfo = self._window_info(s, bars)
        history_short = p0_idx < int(winfo.get("warmup") or 0)
        resolved = max(1, int(winfo["resolved"]))
        start_idx = max(0, p0_idx + 1 - resolved)
        eval_start = p0_idx - start_idx
        eval_end = bn_idx - start_idx
        view = [dict(b) for b in bars[start_idx:bn_idx + 1]]
        spec = {
            "api": 1, "engine": "builtin", "bars": view,
            "strategy": {"source": s["source"]},
            "run": {
                "initial_cash": float(s.get("initial_cash") or 10000.0),
                "fee_bps": float(s.get("fee_bps") or 0.0),
                "slippage_bps": float(s.get("slippage_bps") or 0.0),
                "direction": s.get("direction") or "long_only",
                "params": s.get("params") or {},
                "eval_start": int(eval_start),
                "eval_end": int(eval_end),
                "start_flat": True,
                "flatten": False,
            },
            "timeframe": s["timeframe"],
        }
        if s.get("protection"):
            spec["run"]["protection"] = s["protection"]
        try:
            bt = engine_runner.run_spec(spec, timeout=float(timeout or 120.0))
        except engine_runner.EngineRunError as exc:
            return {"error": f"{exc.code}: {exc.message}", "code": exc.code,
                    "detail": exc.to_dict()}

        paper_fills = list((s.get("state") or {}).get("fills") or [])
        paper_trades = list((s.get("state") or {}).get("trades") or [])
        eq = self.store.load_paper_equity(session_id, 0, 0)
        paper_points = [[int(t), float(v)] for t, v in (eq.get("points") or [])
                        if int(t) > p0]
        report = self._compare_reconcile(
            s, p0, bn, winfo, paper_points, paper_fills, paper_trades, bt,
            events=events, coverage_bars=bn_idx - p0_idx + 1,
            history_short=history_short)
        if save_result:
            rid = self._save_reconcile_result(s, view, bt, report)
            if rid:
                report["result_id"] = rid
        now = _now_ms()
        report["generated_at"] = now
        summary = {
            "generated_at": now,
            "verdict": report["verdict"],
            "coverage": report["coverage"],
            "window": report["window"],
            "paper": report["paper"],
            "backtest": report["backtest"],
            "diff_counts": report["diff_counts"],
            "explanations": report["explanations"],
            "warnings": report["warnings"],
        }
        if report.get("result_id"):
            summary["result_id"] = report["result_id"]
        ev = {"ts": now, "bar_ts": bn, "kind": "reconcile",
              "payload": summary}
        with self._lock:
            cur = self._get(session_id)
            if not cur:
                return {"error": "PAPER_NOT_FOUND: 会话不存在", "code": "PAPER_NOT_FOUND"}
            # 状态里留完整报告（含前 20 条差异），刷新后仍能看到明细；
            # 事件里只留摘要，避免账本重复膨胀。
            cur["state"]["last_reconcile"] = report
            if self.store:
                self.store.save_paper_step(session_id, state=cur["state"], events=[ev])
        self._broadcast_events(s, [ev])
        return report

    def _all_events(self, session_id: str) -> list[dict]:
        out, after = [], 0
        while True:
            page = self.store.load_paper_events(session_id, after, 1000)
            items = page.get("items") or []
            out.extend(items)
            if not page.get("truncated") or not items:
                return out
            after = int(page.get("next_after_seq") or after)

    @staticmethod
    def _close_num(a, b, tol=1e-8) -> bool:
        try:
            return abs(float(a) - float(b)) <= max(tol, abs(float(b)) * tol)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _diff_item(msg: str, **kw) -> dict:
        out = {"message": msg}
        out.update(kw)
        return out

    def _compare_reconcile(self, s, p0, bn, winfo, paper_points, paper_fills,
                           paper_trades, bt, events=None, coverage_bars=0,
                           history_short=False) -> dict:
        tol = 1e-6
        bt_points = [[int(t), float(v)] for t, v in
                     zip((bt.get("equity") or {}).get("times") or [],
                         (bt.get("equity") or {}).get("values") or [])]
        bt_points = [p for p in bt_points if p[0] > p0]
        bt_fills = list(bt.get("fills") or [])
        bt_trades = list(bt.get("trades") or [])

        p_eq = {int(t): float(v) for t, v in paper_points}
        b_eq = {int(t): float(v) for t, v in bt_points}
        times = sorted(set(p_eq) | set(b_eq))
        eq_items, max_abs, max_rel = [], 0.0, 0.0
        for t in times:
            if t not in p_eq or t not in b_eq:
                eq_items.append(self._diff_item(
                    "权益点缺失", time=t, paper=p_eq.get(t), backtest=b_eq.get(t)))
                continue
            d = abs(p_eq[t] - b_eq[t])
            rel = d / max(1e-12, abs(b_eq[t]))
            max_abs, max_rel = max(max_abs, d), max(max_rel, rel)
            if d > max(tol, abs(b_eq[t]) * tol):
                eq_items.append(self._diff_item(
                    "权益不一致", time=t, paper=p_eq[t], backtest=b_eq[t],
                    diff=d))
        eq_ok = not eq_items

        used = set()
        missing, extra, mismatch = [], [], []
        for f in paper_fills:
            hit = None
            for i, b in enumerate(bt_fills):
                if i in used or int(b.get("time") or 0) != int(f.get("time") or 0):
                    continue
                if (float(b.get("signed_qty") or 0) > 0) != (float(f.get("signed_qty") or 0) > 0):
                    continue
                hit = i
                break
            if hit is None:
                missing.append(self._paper_fill_view(f))
                continue
            used.add(hit)
            b = bt_fills[hit]
            bad = []
            if not self._close_num(f.get("price"), b.get("price")):
                bad.append(("price", f.get("price"), b.get("price")))
            if not self._close_num(f.get("signed_qty"), b.get("signed_qty"), 1e-8):
                bad.append(("signed_qty", f.get("signed_qty"), b.get("signed_qty")))
            if not self._close_num(f.get("fee"), b.get("fee"), 1e-7):
                bad.append(("fee", f.get("fee"), b.get("fee")))
            if str(f.get("reason") or "") != str(b.get("reason") or ""):
                bad.append(("reason", f.get("reason"), b.get("reason")))
            if bad:
                mismatch.append({"paper": self._paper_fill_view(f),
                                 "backtest": self._paper_fill_view(b),
                                 "fields": [x[0] for x in bad]})
        for i, b in enumerate(bt_fills):
            if i not in used:
                extra.append(self._paper_fill_view(b))

        p_tr = {self._trade_key(t): t for t in paper_trades}
        b_tr = {self._trade_key(t): t for t in bt_trades}
        tr_missing = [self._trade_view(p_tr[k]) for k in sorted(set(p_tr) - set(b_tr))]
        tr_extra = [self._trade_view(b_tr[k]) for k in sorted(set(b_tr) - set(p_tr))]
        tr_mismatch = []
        for k in sorted(set(p_tr) & set(b_tr)):
            a, b = p_tr[k], b_tr[k]
            fields = []
            if str(a.get("side") or "") != str(b.get("side") or ""):
                fields.append("side")
            for f in ("size", "entry_price", "exit_price", "pnl"):
                if not self._close_num(a.get(f), b.get(f), 1e-8):
                    fields.append(f)
            if fields:
                tr_mismatch.append({"fields": fields,
                                    "paper": self._trade_view(a),
                                    "backtest": self._trade_view(b)})
        fills_ok = not (missing or extra or mismatch)
        trades_ok = not (tr_missing or tr_extra or tr_mismatch)

        explanations = []
        if history_short:
            explanations.append({
                "code": "PAPER_HISTORY_MISSING",
                "message": "当前行情在首个决策前不足 WARMUP，回测无法复现最早几根决策；"
                           "结论只覆盖可重建区间",
            })
        if winfo.get("short"):
            explanations.append({
                "code": "PAPER_WINDOW_INSUFFICIENT",
                "message": f"paper 实际只有 {winfo['actual']} 根，"
                           f"不足 WARMUP={winfo['warmup']}；回测无法复现策略输出",
            })
        evs = events if events is not None else self._all_events(s["session_id"])
        if any(e.get("kind") == "warning"
               and (e.get("payload") or {}).get("code") == "PAPER_RESUME_SKIP"
               for e in evs):
            explanations.append({
                "code": "PAPER_RESUME_SKIP",
                "message": "会话暂停/恢复时跳过过 bar；区间回测会处理这些 bar",
            })
        revised = []
        bars_now = self.service.state.get_ohlcv(s["board_id"], s["timeframe"]) or []
        ts_now = [int(b["timestamp"]) for b in bars_now]
        for ev in evs:
            if ev.get("kind") != "decision":
                continue
            ts = ev.get("bar_ts")
            if ts is None:
                continue
            idx = bisect_left(ts_now, int(ts))
            if idx < len(bars_now) and int(bars_now[idx]["timestamp"]) == int(ts):
                payload = ev.get("payload") or {}
                if "close" in payload and not self._close_num(payload["close"], bars_now[idx]["close"]):
                    revised.append(ts)
        if revised:
            explanations.append({
                "code": "PAPER_BAR_REVISED",
                "message": f"{len(revised)} 根决策 bar 的收盘价在当前行情中已变化",
                "bar_ts": revised[:20],
            })
        has_diff = not (eq_ok and fills_ok and trades_ok)
        if has_diff and not any(e["code"] in ("PAPER_RESUME_SKIP", "PAPER_BAR_REVISED",
                                              "PAPER_WINDOW_INSUFFICIENT",
                                              "PAPER_HISTORY_MISSING") for e in explanations):
            explanations.append({
                "code": "PAPER_NON_CAUSAL_OR_LOOKAHEAD",
                "message": "区间回测与逐窗求值不一致；策略可能依赖未来 bar 或全局长度",
            })
        verdict = "match" if not has_diff else (
            "explainable" if any(e["code"] in (
                "PAPER_WINDOW_INSUFFICIENT", "PAPER_RESUME_SKIP", "PAPER_BAR_REVISED",
                "PAPER_HISTORY_MISSING",
                "PAPER_NON_CAUSAL_OR_LOOKAHEAD") for e in explanations) else "mismatch")
        return {
            "session_id": s["session_id"],
            "verdict": verdict,
            "match": not has_diff,
            "coverage": {"from": p0, "to": bn,
                          "bars": int(coverage_bars or len(set(p_eq) | set(b_eq)))},
            "window": winfo,
            "paper": {"equity_points": len(p_eq), "fills": len(paper_fills),
                      "trades": len(paper_trades),
                      "final_equity": paper_points[-1][1] if paper_points else None},
            "backtest": {"equity_points": len(b_eq), "fills": len(bt_fills),
                         "trades": len(bt_trades),
                         "final_equity": bt_points[-1][1] if bt_points else None},
            "diff_counts": {"equity": len(eq_items), "fills_missing": len(missing),
                            "fills_extra": len(extra), "fills_mismatch": len(mismatch),
                            "trades_missing": len(tr_missing),
                            "trades_extra": len(tr_extra),
                            "trades_mismatch": len(tr_mismatch)},
            "diff": {
                "equity": {"count": len(eq_items), "max_abs": max_abs,
                           "max_rel": max_rel, "items": eq_items[:20]},
                "fills": {"missing": missing[:20], "extra": extra[:20],
                          "mismatch": mismatch[:20]},
                "trades": {"missing": tr_missing[:20], "extra": tr_extra[:20],
                           "mismatch": tr_mismatch[:20]},
            },
            "explanations": explanations,
            "warnings": list(bt.get("warnings") or []),
        }

    @staticmethod
    def _paper_fill_view(f: dict) -> dict:
        return {k: f.get(k) for k in
                ("time", "action", "signed_qty", "price", "fee", "reason")}

    @staticmethod
    def _trade_key(t: dict):
        return (int(t.get("entry_time") or 0), int(t.get("exit_time") or 0),
                str(t.get("side") or ""))

    @staticmethod
    def _trade_view(t: dict) -> dict:
        return {k: t.get(k) for k in
                ("side", "size", "entry_time", "exit_time", "entry_price",
                 "exit_price", "pnl", "exit_reason")}

    def delete(self, session_id: str, delete_result: bool = False) -> dict:
        """删除非运行中的会话及其账本；运行中必须先 stop（防误删现场）。

        停止后物化的结果默认保留（它是冻结结果，可在结果栏单独删）；
        delete_result=True 时一并删。
        """
        with self._lock:
            s = self._get(session_id)
            if not s:
                return {"error": "PAPER_NOT_FOUND: 会话不存在", "code": "PAPER_NOT_FOUND"}
            if s.get("status") == "running":
                return {"error": "PAPER_RUNNING: 运行中的模拟盘不能删除，请先停止",
                        "code": "PAPER_RUNNING"}
            rid = s.get("result_id")
            self.sessions.pop(session_id, None)
            ev = self._wake.pop(session_id, None)
            if ev:
                ev.set()
            self._threads.pop(session_id, None)
            if self.store:
                self.store.delete_paper_session(session_id)
        if delete_result and rid:
            try:
                self.service.delete_result(rid)
            except Exception:
                logger.exception("paper 结果删除失败: %s", rid)
        self._bc("paper_deleted", s)
        return {"status": "deleted", "session_id": session_id,
                "result_id": rid, "result_kept": bool(rid and not delete_result)}

    def on_board_deleted(self, board_id: str) -> None:
        with self._lock:
            ids = [sid for sid, s in self.sessions.items() if s["board_id"] == board_id]
            for sid in ids:
                s = self.sessions.pop(sid, None)
                if s:
                    s["status"] = "stopped"
                ev = self._wake.get(sid)
                if ev:
                    ev.set()
            # 库侧有 FK CASCADE；这里只清内存 worker
        if ids:
            logger.info("paper 会话随画板删除: %d", len(ids))

    def on_timeframe_deleted(self, board_id: str, timeframe: str) -> None:
        """周期被删：会话保留现场但转 paused，避免 worker 对着空行情空转。"""
        evs = []
        with self._lock:
            for s in self.sessions.values():
                if (s["board_id"] == board_id and s["timeframe"] == timeframe
                        and s["status"] == "running"):
                    ev = {"ts": _now_ms(), "bar_ts": s.get("last_seen_ts"),
                          "kind": "paused",
                          "payload": {"reason": "TIMEFRAME_DELETED"}}
                    s["status"] = "paused"
                    if self.store:
                        self.store.save_paper_step(
                            s["session_id"], state=s["state"], events=[ev],
                            status="paused")
                    self._wake.setdefault(s["session_id"], threading.Event()).set()
                    evs.append((s, ev))
        for s, ev in evs:
            self._broadcast_events(s, [ev])
            self._bc("paper_paused", s)

    def stop_all(self) -> None:
        with self._lock:
            for sid, s in list(self.sessions.items()):
                if s.get("status") == "running":
                    s["status"] = "paused"
                ev = self._wake.get(sid)
                if ev:
                    ev.set()

    # ---------------------------- 数据回调 ----------------------------
    def is_active_timeframe(self, board_id: str, timeframe: str) -> bool:
        """该槽是否有 running 的模拟盘；用于豁免数据源不可见槽降频。"""
        with self._lock:
            return any(s.get("board_id") == board_id
                       and s.get("timeframe") == timeframe
                       and s.get("status") == "running"
                       for s in self.sessions.values())

    def on_bars(self, board_id: str, timeframe: str, existing=None, merged=None) -> None:
        """数据源轮询合并新 bar 后调用；只唤醒，不做任何重活。"""
        with self._lock:
            for sid, s in self.sessions.items():
                if (s["board_id"] == board_id and s["timeframe"] == timeframe
                        and s["status"] == "running"):
                    self._wake.setdefault(sid, threading.Event()).set()

    # ---------------------------- worker ----------------------------
    def _worker(self, session_id: str, ev: threading.Event) -> None:
        while True:
            ev.wait()
            ev.clear()
            s = self._get(session_id)
            if not s or s.get("status") in _TERMINAL:
                break
            if s.get("status") != "running":
                continue
            try:
                self._process(session_id)
            except Exception as exc:  # noqa: BLE001 - 单会话失败不能拖死线程
                logger.exception("paper worker 失败: %s", session_id)
                self._fail(session_id, exc)

    def _process(self, session_id: str, now_ms: int = None) -> None:
        with self._lock:
            s = self._get(session_id)
            if not s or s.get("status") != "running" or session_id in self._processing:
                return
            self._processing.add(session_id)
        try:
            self._process_steps(session_id, now_ms)
        finally:
            with self._lock:
                self._processing.discard(session_id)

    def _process_steps(self, session_id: str, now_ms: int = None) -> None:
        s = self._get(session_id)
        if not s:
            return
        bars = self.service.state.get_ohlcv(s["board_id"], s["timeframe"]) or []
        if not bars:
            return
        now = int(now_ms or _now_ms())
        closed = [b for b in bars if _is_closed(b, s["timeframe"], now, self.settle_ms)]
        if not closed:
            return
        latest = closed[-1]
        last_seen = s.get("last_seen_ts")
        # 用 last_seen 判新 bar（cursor 是最后决策 bar P，天然落后一根，不能拿来去重）
        new = [b for b in closed
               if last_seen is None or int(b["timestamp"]) > int(last_seen)]
        if not new:
            if int(latest["timestamp"]) > int(s.get("last_seen_ts") or 0):
                s["last_seen_ts"] = int(latest["timestamp"])
                if self.store:
                    self.store.save_paper_step(
                        session_id, state=s["state"],
                        last_seen_ts=s["last_seen_ts"])
            return
        if len(new) > self.max_catchup:
            self._pause_gap(s, len(new), new[0], new[-1])
            return

        ts_list = [int(b["timestamp"]) for b in bars]
        for B in new:
            with self._lock:
                s = self._get(session_id)
                if not s or s.get("status") != "running":
                    return
            b_idx = bisect_left(ts_list, int(B["timestamp"]))
            p_idx = b_idx - 1
            if p_idx < 0:
                s["cursor_ts"] = int(B["timestamp"])
                s["last_seen_ts"] = int(B["timestamp"])
                if self.store:
                    self.store.save_paper_step(
                        session_id, state=s["state"],
                        cursor_ts=s["cursor_ts"], last_seen_ts=s["last_seen_ts"])
                continue
            P = bars[p_idx]
            limit = int(s.get("window_bars") or s["state"].get("window_resolved")
                        or AUTO_WINDOW_MIN)
            window = bars[max(0, p_idx + 1 - limit):p_idx + 1]
            actual = len(window)
            short = actual <= int(s["state"].get("warmup") or 0)
            truncated = (p_idx + 1) > actual
            s["state"]["window_actual"] = actual
            s["state"]["window_short"] = short
            s["state"]["window_truncated"] = truncated
            spec = {
                "api": 1, "engine": "builtin", "bars": window,
                "strategy": {"source": s["source"]},
                "run": {"params": s.get("params") or {},
                        "direction": s.get("direction") or "long_only"},
                "timeframe": s["timeframe"],
            }
            try:
                out = engine_runner.signal_spec(spec, timeout=60.0)
            except engine_runner.EngineRunError as exc:
                raise RuntimeError(f"{exc.code}: {exc.message}") from exc
            target = float(out.get("target") or 0.0)
            # 成交 reason 与回测驱动保持同一口径：空 reason 非零仓由撮合器补 signal，
            # 平仓由撮合器补 target_flat；这里不要把空串提前变成 signal。
            raw_reason = str(out.get("reason") or "")
            reason = raw_reason or "signal"
            for w in (out.get("warnings") or []):
                self._warn_once(s, str(w), P["timestamp"])

            matcher = self._matcher(s)
            # 撮合器需要 bar index 才能算 fill.index / holding_bars；state 的 bar 没有该字段
            B2 = dict(B)
            B2["index"] = b_idx
            fills = matcher.execute_target(
                B2, target, matcher.equity(float(B2["open"])), raw_reason)
            fills += matcher.check_protection(B2, s.get("protection"))
            equity = matcher.equity(float(B2["close"]))
            snap = matcher.snapshot()
            state = s["state"]
            state.update(snap)
            state["equity"] = equity
            state["bars_processed"] = int(state.get("bars_processed") or 0) + 1
            state["last_decision"] = {
                "bar_ts": int(P["timestamp"]), "target": target, "reason": reason,
                "close": float(P["close"]), "at": now,
            }
            if fills:
                state["last_fill"] = fills[-1]

            evs = [{"ts": now, "bar_ts": int(P["timestamp"]), "kind": "decision",
                    "payload": {"target": target, "reason": reason,
                                "close": float(P["close"]),
                                "bar_ts": int(P["timestamp"])}}]
            for f in fills:
                evs.append({"ts": now, "bar_ts": int(B["timestamp"]), "kind": "fill",
                            "payload": dict(f)})
            evs.append({"ts": now, "bar_ts": int(B["timestamp"]), "kind": "equity",
                        "payload": {"equity": equity, "cash": matcher.cash,
                                    "pos": matcher.pos, "price": float(B["close"])}})
            s["cursor_ts"] = int(P["timestamp"])
            s["last_seen_ts"] = int(B["timestamp"])
            with self._lock:
                cur = self._get(session_id)
                if not cur or cur.get("status") != "running":
                    return
            if self.store:
                self.store.save_paper_step(
                    session_id, state=state, events=evs,
                    equity_points=[[int(B["timestamp"]), equity]],
                    cursor_ts=s["cursor_ts"], last_seen_ts=s["last_seen_ts"])
            self._broadcast_events(s, evs)

    def _pause_gap(self, s: dict, n: int, first: dict, last: dict) -> None:
        now = _now_ms()
        ev = {"ts": now, "bar_ts": int(last["timestamp"]), "kind": "warning",
              "payload": {"code": "PAPER_GAP_TOO_LARGE",
                          "message": f"待处理 {n} 根 > 上限 {self.max_catchup}，已暂停",
                          "bars": n}}
        s["status"] = "paused_gap"
        if self.store:
            self.store.save_paper_step(s["session_id"], state=s["state"], events=[ev],
                                       status="paused_gap")
        self._broadcast_events(s, [ev])
        self._bc("paper_paused", s)

    def _fail(self, session_id: str, exc: Exception) -> None:
        with self._lock:
            s = self._get(session_id)
            if not s:
                return
            msg = f"{type(exc).__name__}: {exc}"
            s["status"] = "error"
            s["last_error"] = msg[:2000]
            ev = {"ts": _now_ms(), "bar_ts": s.get("last_seen_ts"), "kind": "error",
                  "payload": {"code": "PAPER_ERROR", "message": msg[:2000]}}
            if self.store:
                self.store.save_paper_step(session_id, state=s["state"], events=[ev],
                                           status="error", last_error=msg[:2000])
        self._broadcast_events(s, [ev])
        self._bc("paper_error", s)

    # ---------------------------- 结果物化 ----------------------------
    def _save_reconcile_result(self, s: dict, bars: list[dict], bt: dict,
                               report: dict):
        """把对账用的区间回测登记成普通结果，供结果栏画到 K 线上。"""
        if not self.store:
            return None
        eq = bt.get("equity") or {}
        times = [int(t) for t in (eq.get("times") or [])]
        values = [float(v) for v in (eq.get("values") or [])]
        if not times or len(times) != len(values):
            return None
        # 同一会话、同一覆盖区间只保留一条对账结果；重复点击直接返回已有结果。
        key = hashlib.sha256(
            f"{s['session_id']}|{times[0]}|{times[-1]}|{s.get('script_sha256')}|"
            f"{s.get('direction')}|{s.get('initial_cash')}".encode("utf-8")
        ).hexdigest()[:20]
        board_obj = self.service.state.get_board(s["board_id"])
        for rid, old in ((board_obj.results if board_obj else {}) or {}).items():
            batch = old.get("batch") or {}
            if batch.get("kind") == "paper_reconcile" and batch.get("reconcile_key") == key:
                return rid
        cash = float(s.get("initial_cash") or 10000.0)
        if abs(values[0] - cash) > max(1e-6, abs(cash) * 1e-6):
            step = _tf_ms(s["timeframe"]) or 60_000
            times = [times[0] - step] + times
            values = [cash] + values
        eng = bt.get("engine") or {}
        asm = bt.get("assumptions") or {}
        payload = {
            "kind": "paper_reconcile",
            "board_id": s["board_id"], "timeframe": s["timeframe"],
            "status": bt.get("status"),
            "equity": {"times": times, "values": values},
            "trades": bt.get("trades") or [],
            "fills": bt.get("fills") or [],
            "warnings": list(bt.get("warnings") or []) + ["PAPER_RECONCILE_RESULT"],
            "run": {"initial_cash": cash,
                    "fee": float(s.get("fee_bps") or 0.0) / 10_000.0,
                    "slippage": float(s.get("slippage_bps") or 0.0) / 10_000.0,
                    "leverage": 1.0,
                    "bars_per_year": asm.get("bars_per_year")},
            "engine": {
                "id": str(eng.get("id") or "builtin"),
                "version": str(eng.get("version") or self.service.VERSION),
                "caps": eng.get("caps") if isinstance(eng.get("caps"), dict) else {},
                "config": {"direction": s.get("direction") or "long_only",
                           "fee_bps": s.get("fee_bps"),
                           "slippage_bps": s.get("slippage_bps"),
                           "params": s.get("params") or {}},
            },
            "strategy": {
                "id": s["script"], "mode": "signal",
                "params": s.get("params") or {},
                "warmup": int((s.get("state") or {}).get("warmup") or 0),
                "protection": s.get("protection") or {},
                "source": s["source"],
                "source_sha256": s.get("script_sha256") or "",
            },
            "execution_assumptions": asm,
            "data": {"requested": {"from": times[0], "to": times[-1]}},
            "display_name": "模拟盘对账 · " + (
                (s.get("state") or {}).get("strategy_name")
                or str(s.get("script") or "").split("/")[-1] or "paper"),
            "batch": {"kind": "paper_reconcile", "session_id": s["session_id"],
                      "reconcile_key": key},
        }
        lock = (self.service.state.get_board(s["board_id"]).source_lock or {})
        out = normalize_result(
            payload, s["board_id"], s["timeframe"], bars=bars,
            version=self.service.VERSION,
            source_sha256=s.get("script_sha256"),
            symbol=(lock.get("identity") or {}).get("symbol"),
            source_script=s["script"],
        )
        if out.get("error"):
            logger.warning("对账结果校验失败: %s", out["error"])
            return None
        res = out["result"]
        res["result_id"] = next_result_id(
            (self.service.state.get_board(s["board_id"]).results or {}).keys(),
            res["strategy"]["id"])
        res["batch"] = {"kind": "paper_reconcile", "session_id": s["session_id"],
                        "reconcile_key": key}
        add = self.service.state.add_result(s["board_id"], res)
        if add.get("error"):
            logger.warning("对账结果登记失败: %s", add["error"])
            return None
        self.service._bc_result_created(s["board_id"], s["timeframe"],
                                        summarize(res), add)
        return res["result_id"]

    def _materialize_result(self, s: dict):
        if not self.store:
            return None
        eq = self.store.load_paper_equity(s["session_id"], 0, 0)
        points = eq.get("points") or []
        if not points:
            return None
        times = [int(p[0]) for p in points]
        values = [float(p[1]) for p in points]
        cash = float(s.get("initial_cash") or 10000.0)
        if abs(values[0] - cash) > max(1e-6, abs(cash) * 1e-6):
            times = [times[0] - 1] + times
            values = [cash] + values
        m = self._matcher(s)
        fills = m.fills
        trades = m.trades
        status = ("no_signals" if not fills
                  else "open_position_only" if not trades else "completed_trades")
        bpy = bars_per_year(s["timeframe"]) or 365
        payload = {
            "kind": "paper",
            "board_id": s["board_id"], "timeframe": s["timeframe"],
            "status": status,
            "equity": {"times": times, "values": values},
            "trades": trades, "fills": fills,
            "warnings": ["PAPER_SESSION_STOPPED"],
            "run": {"initial_cash": cash, "fee": float(s["fee_bps"]) / 10_000.0,
                    "slippage": float(s["slippage_bps"]) / 10_000.0,
                    "leverage": 1.0, "bars_per_year": bpy},
            "engine": {"id": "builtin", "version": self.service.VERSION,
                       "config": {"direction": s["direction"],
                                  "fee_bps": s["fee_bps"],
                                  "slippage_bps": s["slippage_bps"],
                                  "params": s.get("params") or {}}},
            "strategy": {"id": s["script"], "mode": "signal",
                         "params": s.get("params") or {},
                         "warmup": int((s.get("state") or {}).get("warmup") or 0),
                         "protection": s.get("protection") or {},
                         "source": s["source"]},
            "execution_assumptions": {
                "fill_rule": "next_open", "bar_close_policy": "closed_bars_only",
                "intrabar_mode": "conservative", "leverage": 1,
                "fee_bps": s["fee_bps"], "slippage_bps": s["slippage_bps"],
                "protection_rule": ("gap_open_then_intrabar_trigger"
                                    if s.get("protection") else "none"),
                "direction": s["direction"], "calendar": "bar_clock",
            },
            "data": {"requested": {"from": times[0], "to": times[-1]}},
            "display_name": f"模拟盘 · {str(s['script']).split('/')[-1]}",
        }
        bars = self.service.state.get_ohlcv(s["board_id"], s["timeframe"]) or []
        lock = (self.service.state.get_board(s["board_id"]).source_lock or {})
        out = normalize_result(payload, s["board_id"], s["timeframe"], bars=bars,
                               version=self.service.VERSION,
                               source_sha256=s.get("script_sha256"),
                               symbol=(lock.get("identity") or {}).get("symbol"),
                               source_script=s["script"])
        if out.get("error"):
            logger.warning("paper 结果校验失败: %s", out["error"])
            return None
        res = out["result"]
        res["result_id"] = next_result_id(
            (self.service.state.get_board(s["board_id"]).results or {}).keys(),
            res["strategy"]["id"])
        res["batch"] = {"kind": "paper", "session_id": s["session_id"]}
        res["stats"]["total_fees"] = sum(float(f.get("fee") or 0.0) for f in fills)
        res["data"]["fingerprint"] = self.service._data_fingerprint(bars)
        add = self.service.state.add_result(s["board_id"], res)
        if add.get("error"):
            logger.warning("paper 结果登记失败: %s", add["error"])
            return None
        self.service._bc_result_created(s["board_id"], s["timeframe"], summarize(res), add)
        return res["result_id"]

    # ---------------------------- 小工具 ----------------------------
    def _get(self, session_id: str):
        return self.sessions.get(session_id)

    def _matcher(self, s: dict) -> MatchingEngine:
        m = MatchingEngine(float(s.get("initial_cash") or 10000.0),
                           float(s.get("fee_bps") or 0.0),
                           float(s.get("slippage_bps") or 0.0))
        state = s.get("state") or {}
        if state:
            try:
                m.restore(state)
            except Exception:
                logger.exception("paper 撮合状态恢复失败，按空仓重建: %s", s.get("session_id"))
        # 兼容 0.7.0 早期账本：paper 的 bar 没带 index，fill.index=-1、holding_bars=0；
        # 用当前 K 线时间轴补回，不改价格/数量/现金。
        bars = self.service.state.get_ohlcv(s["board_id"], s["timeframe"]) or []
        idx_by_ts = {int(b["timestamp"]): i for i, b in enumerate(bars)}
        if m._trade is not None and int(getattr(m._trade, "entry_index", -1)) < 0:
            m._trade.entry_index = idx_by_ts.get(int(m._trade.entry_time), -1)
        for t in m.trades:
            # 不用历史 index：回补历史会让所有下标整体平移，必须按时间戳重算
            ei = idx_by_ts.get(int(t.get("entry_time") or 0), -1)
            xi = idx_by_ts.get(int(t.get("exit_time") or 0), -1)
            if ei >= 0 and xi >= 0:
                t["holding_bars"] = max(0, xi - ei)
        for f in m.fills:
            i = idx_by_ts.get(int(f.get("time") or 0))
            if i is not None:
                f["index"] = i
        return m

    def _window_info(self, s: dict, bars: list[dict] = None) -> dict:
        st = s.get("state") or {}
        resolved = int(st.get("window_resolved") or s.get("window_bars")
                       or self.window_bars or AUTO_WINDOW_MIN)
        if resolved <= 0:
            resolved = AUTO_WINDOW_MIN
        mode = st.get("window_mode") or "manual"
        requested = st.get("window_requested")
        if mode == "auto":
            requested = None
        warmup = int(st.get("window_warmup") or st.get("warmup") or 0)
        actual = st.get("window_actual")
        if bars and s.get("cursor_ts") is not None:
            # 以游标 P 为准重算，避免创建时/启动后行情新增导致 actual 陈旧
            cursor = int(s.get("cursor_ts") or 0)
            idx = -1
            for i, b in enumerate(bars):
                if int(b.get("timestamp") or 0) <= cursor:
                    idx = i
                else:
                    break
            if idx >= 0:
                actual = min(resolved, idx + 1)
        if actual is not None:
            actual = max(0, min(int(actual), resolved))
        short = bool(st.get("window_short")) if actual is None else actual <= warmup
        truncated = bool(st.get("window_truncated"))
        if bars and actual is not None:
            truncated = len(bars) > actual
        return {
            "mode": mode,
            "requested": requested,
            "resolved": resolved,
            "actual": actual,
            "warmup": warmup,
            "short": short,
            "truncated": truncated,
            "adjusted": bool(st.get("window_adjusted")),
        }

    def _public(self, s: dict, include_details: bool = False) -> dict:
        out = copy.deepcopy({k: v for k, v in s.items() if k != "state"})
        st = s.get("state") or {}
        winfo = self._window_info(s)
        out.update({
            "equity": st.get("equity", s.get("initial_cash")),
            "cash": st.get("cash", s.get("initial_cash")),
            "position": st.get("pos", 0.0),
            "avg_price": st.get("avg_price", 0.0),
            "bars_processed": st.get("bars_processed", 0),
            "last_decision": st.get("last_decision"),
            "last_fill": st.get("last_fill"),
            "window": winfo,
            "window_mode": winfo["mode"],
            "window_requested": winfo["requested"],
            "window_resolved": winfo["resolved"],
            "window_actual": winfo["actual"],
            "window_short": winfo["short"],
            "window_truncated": winfo["truncated"],
            "trade_count": len(st.get("trades") or []),
            "fill_count": len(st.get("fills") or []),
            "strategy_name": st.get("strategy_name") or (s.get("strategy_name") or ""),
        })
        out.pop("source", None)

        if include_details:
            m = self._matcher(s)
            snap = m.snapshot()
            trades = snap.get("trades") or []
            fills = snap.get("fills") or []
            bars = self.service.state.get_ohlcv(s["board_id"], s["timeframe"]) or []
            last_price = float(bars[-1]["close"]) if bars else None
            pos = float(st.get("pos") or 0.0)
            avg = float(st.get("avg_price") or 0.0)
            cash = float(st.get("cash") or 0.0)
            init = float(s.get("initial_cash") or 10000.0)
            live_equity = (cash + pos * last_price) if last_price is not None else float(
                st.get("equity") or init)
            unrealized = (pos * (last_price - avg)) if (last_price is not None and pos) else 0.0
            notional = abs(pos * avg) if pos else 0.0
            realized = sum(float(t.get("pnl") or 0.0) for t in trades)
            fees = sum(float(f.get("fee") or 0.0) for f in fills)
            open_trade = None
            trade = snap.get("trade")
            if pos and isinstance(trade, dict):
                entry_idx = int(trade.get("entry_index", -1))
                cur_idx = len(bars) - 1
                open_trade = {
                    "side": "long" if pos > 0 else "short",
                    "entry_time": trade.get("entry_time"),
                    "entry_price": avg,
                    "size": abs(pos),
                    "notional": notional,
                    "fee": float(trade.get("fee") or 0.0),
                    "entry_reason": trade.get("entry_reason") or "",
                    "holding_bars": max(0, cur_idx - entry_idx) if entry_idx >= 0 else None,
                    "pnl": unrealized,
                    "pnl_pct": (unrealized / notional) if notional else 0.0,
                    "status": "open",
                }
            winfo = self._window_info(s, bars)
            last_rep = st.get("last_reconcile")
            if isinstance(last_rep, dict) and last_rep.get("result_id"):
                board = self.service.state.get_board(s["board_id"])
                if board and last_rep["result_id"] not in (board.results or {}):
                    last_rep = dict(last_rep)
                    last_rep.pop("result_id", None)
                    last_rep["result_missing"] = True
            out.update({
                "window": winfo,
                "window_mode": winfo["mode"],
                "window_requested": winfo["requested"],
                "window_resolved": winfo["resolved"],
                "window_actual": winfo["actual"],
                "window_short": winfo["short"],
                "window_truncated": winfo["truncated"],
                "initial_cash": init,
                "last_price": last_price,
                "last_price_ts": int(bars[-1]["timestamp"]) if bars else None,
                "live_equity": live_equity,
                "position_side": "long" if pos > 0 else "short" if pos < 0 else "flat",
                "position_notional": notional,
                "unrealized_pnl": unrealized,
                "unrealized_pct": (unrealized / notional) if notional else 0.0,
                "realized_pnl": realized,
                "total_fees": fees,
                "total_pnl": live_equity - init,
                "total_return": (live_equity - init) / init if init else 0.0,
                "open_trade": open_trade,
                "trades": trades,
                "fills": fills,
                "last_reconcile": last_rep,
            })
        return out

    def _warn_once(self, s: dict, message: str, bar_ts: int,
                   code: str = "PAPER_WARNING", extra: dict = None) -> None:
        seen = s["state"].setdefault("warnings_seen", [])
        if message in seen:
            return
        seen.append(message)
        if len(seen) > 50:
            seen[:] = seen[-50:]
        payload = {"code": code, "message": message}
        if extra:
            payload.update(extra)
        self._append_event(s, {"ts": _now_ms(), "bar_ts": bar_ts, "kind": "warning",
                               "payload": payload})

    def _append_event(self, s: dict, ev: dict) -> None:
        if self.store:
            self.store.save_paper_step(s["session_id"], state=s["state"], events=[ev])
        self._broadcast_events(s, [ev])

    def _broadcast_events(self, s: dict, events: list[dict]) -> None:
        kinds = {"decision": "paper_decision", "fill": "paper_fill",
                 "equity": "paper_equity", "warning": "paper_warning",
                 "error": "paper_error", "started": "paper_started",
                 "paused": "paper_paused", "resumed": "paper_resumed",
                 "stopped": "paper_stopped", "reconcile": "paper_reconcile"}
        for ev in events:
            typ = kinds.get(ev.get("kind"))
            if not typ:
                continue
            self._bc(typ, s, event=ev)

    def _bc(self, typ: str, s: dict, event: dict = None) -> None:
        msg = {"type": typ, "session_id": s.get("session_id"),
               "board_id": s.get("board_id"), "timeframe": s.get("timeframe"),
               "status": s.get("status"), "equity": (s.get("state") or {}).get("equity")}
        if event:
            msg["event"] = event
        try:
            self.service._bc(msg)
        except Exception:
            logger.debug("paper 广播失败", exc_info=True)
