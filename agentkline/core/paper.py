"""模拟盘（paper）会话 / 账本 / bar 执行器（v0.7.0）。

口径与回测相同：P 收盘算 target，下一根 B 开盘成交，B 的 high/low 查保护，
B 收盘记权益；复用 `MatchingEngine`，不引入“当前价成交”。

0.7.0 只做一个会话一个标的/周期/策略；线程模型是每会话一个 worker，
bar 到达只唤醒 worker，不阻塞数据源轮询线程。
"""
from __future__ import annotations

import copy
import hashlib
import logging
import threading
import time
import uuid
from bisect import bisect_left

from agentkline_engine.matching import MatchingEngine

from ..backtest import runner as engine_runner
from .results import bars_per_year, next_result_id, normalize_result, summarize

logger = logging.getLogger("agentkline.paper")

DEFAULT_WINDOW_BARS = 5000
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


class PaperManager:
    """paper 会话管理器；由 AgentKlineService 持有。"""

    def __init__(self, service):
        self.service = service
        self.store = getattr(service, "store", None)
        limits = getattr(service, "limits", {}) or {}
        self.window_bars = self._clamp_int(
            limits.get("paper_window_bars", DEFAULT_WINDOW_BARS), 100, MAX_WINDOW_BARS)
        self.max_catchup = self._clamp_int(
            limits.get("paper_max_catchup_bars", DEFAULT_MAX_CATCHUP_BARS),
            10, MAX_CATCHUP_BARS)
        self.settle_ms = self._clamp_int(
            limits.get("paper_settle_ms", DEFAULT_SETTLE_MS), 0, 300_000)
        self.sessions: dict[str, dict] = {}
        self._wake: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._processing: set[str] = set()
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
            self.sessions[s["session_id"]] = s
            if s.get("status") == "running":
                self._ensure_worker(s["session_id"])
        if rows:
            logger.info("paper 恢复: %d 个会话（running=%d）", len(rows),
                        sum(1 for s in rows if s.get("status") == "running"))

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
            ev = self.store.load_paper_events(session_id, 0, 30)
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
            state = {
                "cash": cash, "pos": 0.0, "avg_price": 0.0, "equity": cash,
                "fills": [], "trades": [], "trade": None,
                "bars_processed": 0, "last_decision": None, "last_fill": None,
                "window_truncated": False, "warnings_seen": [],
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
                "window_bars": self._clamp_int(window_bars or self.window_bars,
                                               100, MAX_WINDOW_BARS),
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
            latest_ts = int(latest["timestamp"])
            cursor = s.get("cursor_ts") or latest_ts
            skipped = sum(1 for b in bars
                          if int(b["timestamp"]) > int(cursor)
                          and _is_closed(b, s["timeframe"], _now_ms(), self.settle_ms))
            now = _now_ms()
            events = []
            if first:
                events.append({"ts": now, "bar_ts": latest_ts, "kind": "started",
                               "payload": {"cursor_ts": latest_ts,
                                           "last_seen_ts": latest_ts}})
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
            s["state"]["equity"] = self._matcher(s).equity(float(latest["close"]))
            if self.store:
                self.store.update_paper_session(
                    session_id, started_at=s.get("started_at"))
                self.store.save_paper_step(
                    session_id, state=s["state"], events=events,
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
            window = bars[max(0, p_idx + 1 - int(s.get("window_bars") or self.window_bars)):p_idx + 1]
            truncated = (p_idx + 1) > len(window)
            if truncated and not s["state"].get("window_truncated"):
                s["state"]["window_truncated"] = True
                self._append_event(s, {"ts": now, "bar_ts": P["timestamp"],
                                       "kind": "warning",
                                       "payload": {"code": "PAPER_WINDOW_TRUNCATED",
                                                   "message": f"策略窗口截断为最近 {len(window)} 根"}})
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
            reason = str(out.get("reason") or "signal")
            for w in (out.get("warnings") or []):
                self._warn_once(s, str(w), P["timestamp"])

            matcher = self._matcher(s)
            # 撮合器需要 bar index 才能算 fill.index / holding_bars；state 的 bar 没有该字段
            B2 = dict(B)
            B2["index"] = b_idx
            fills = matcher.execute_target(
                B2, target, matcher.equity(float(B2["open"])), reason)
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

    def _public(self, s: dict, include_details: bool = False) -> dict:
        out = copy.deepcopy({k: v for k, v in s.items() if k != "state"})
        st = s.get("state") or {}
        out.update({
            "equity": st.get("equity", s.get("initial_cash")),
            "cash": st.get("cash", s.get("initial_cash")),
            "position": st.get("pos", 0.0),
            "avg_price": st.get("avg_price", 0.0),
            "bars_processed": st.get("bars_processed", 0),
            "last_decision": st.get("last_decision"),
            "last_fill": st.get("last_fill"),
            "window_truncated": bool(st.get("window_truncated")),
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
            out.update({
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
            })
        return out

    def _warn_once(self, s: dict, message: str, bar_ts: int) -> None:
        seen = s["state"].setdefault("warnings_seen", [])
        if message in seen:
            return
        seen.append(message)
        if len(seen) > 50:
            seen[:] = seen[-50:]
        self._append_event(s, {"ts": _now_ms(), "bar_ts": bar_ts, "kind": "warning",
                               "payload": {"code": "PAPER_WARNING", "message": message}})

    def _append_event(self, s: dict, ev: dict) -> None:
        if self.store:
            self.store.save_paper_step(s["session_id"], state=s["state"], events=[ev])
        self._broadcast_events(s, [ev])

    def _broadcast_events(self, s: dict, events: list[dict]) -> None:
        kinds = {"decision": "paper_decision", "fill": "paper_fill",
                 "equity": "paper_equity", "warning": "paper_warning",
                 "error": "paper_error", "started": "paper_started",
                 "paused": "paper_paused", "resumed": "paper_resumed",
                 "stopped": "paper_stopped"}
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
