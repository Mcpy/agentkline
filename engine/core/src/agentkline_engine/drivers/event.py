"""event 驱动：逐 bar 调用 on_bar、只读 ctx、target 收集、state 校验。

时间线与 signal 完全一致：bar t 收盘决策 → t+1 开盘按 target 调仓 → 盘中查保护
→ 收盘记权益；WARMUP 之前的 target 不执行、不计绩效。两条路径共用
`drivers.common` 的方向过滤、保护与结果装配，从而保证跨范式逐笔一致。
"""
from __future__ import annotations

import math

from ..contract import Engine, RunRequest, RunResult
from ..errors import AKError
from ..loader import Strategy, ensure_state_json
from ..matching import MatchingEngine
from .common import apply_direction, deadline_check, finalize_result, merge_protection

_BAR_FIELDS = ("timestamp", "open", "high", "low", "close", "volume")


def _sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


class EventContext:
    """on_bar / init 的只读上下文。

    通过 property 暴露快照，且禁止任何属性赋值；history/position/params 都返回
    副本，用户代码改不动引擎内部状态，也拿不到未来 bar。
    """

    __slots__ = ("_bars", "_t", "_matcher", "_close", "_equity", "_params", "_entry_index")

    def __init__(self, bars: list[dict], t: int, matcher: MatchingEngine,
                 equity: float, params: dict, entry_index: int | None):
        object.__setattr__(self, "_bars", bars)
        object.__setattr__(self, "_t", int(t))
        object.__setattr__(self, "_matcher", matcher)
        object.__setattr__(self, "_equity", float(equity))
        object.__setattr__(self, "_params", dict(params))
        object.__setattr__(self, "_entry_index", entry_index)
        close = float(bars[t]["close"]) if 0 <= t < len(bars) else 0.0
        object.__setattr__(self, "_close", close)

    def __setattr__(self, name, value):  # noqa: D401 - 只读视图
        raise AttributeError(f"ctx 是只读视图，不能设置属性 {name!r}")

    def __delattr__(self, name):
        raise AttributeError(f"ctx 是只读视图，不能删除属性 {name!r}")

    def history(self, n: int, fields=None) -> list[dict]:
        """截至当前 bar（含）的最后 n 根；不足给实际根数。"""
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise AKError("INPUT_INVALID", f"history(n) 的 n 必须是 >= 0 的整数，收到 {n!r}")
        if n == 0 or self._t < 0:
            return []
        if fields is None:
            keys = _BAR_FIELDS
        else:
            if isinstance(fields, str):
                fields = (fields,)
            if not isinstance(fields, (list, tuple)):
                raise AKError("INPUT_INVALID", "history 的 fields 必须是字段名数组或 None")
            unknown = [f for f in fields if f not in _BAR_FIELDS]
            if unknown:
                raise AKError("INPUT_INVALID",
                              f"history 未知字段 {unknown}；可用 {list(_BAR_FIELDS)}")
            wanted = set(fields)
            keys = tuple(f for f in _BAR_FIELDS if f in wanted)
        start = max(0, self._t + 1 - n)
        return [{k: self._bars[i][k] for k in keys} for i in range(start, self._t + 1)]

    @property
    def position(self) -> dict:
        pos = float(self._matcher.pos)
        if pos == 0:
            return {"weight": 0.0, "entry_price": None, "bars_held": 0}
        weight = pos * self._close / self._equity if self._equity > 0 else 0.0
        entry_price = float(self._matcher.avg_price)
        held = self._t - self._entry_index if self._entry_index is not None else 0
        return {"weight": weight, "entry_price": entry_price,
                "bars_held": max(0, int(held))}

    @property
    def cash(self) -> float:
        return float(self._matcher.cash)

    @property
    def equity(self) -> float:
        return float(self._equity)

    @property
    def params(self) -> dict:
        return dict(self._params)

    @property
    def t(self) -> int:
        return self._t


def normalize_event_return(payload, t: int) -> tuple[float, str, bool]:
    """把 on_bar 返回值归一成 (target, reason, 是否裁剪)。"""
    if isinstance(payload, bool):
        raise AKError("ON_BAR_BAD_RETURN",
                      f"on_bar 在 bar {t} 必须返回 float 或 {{'target': float}}，收到布尔值")
    if isinstance(payload, dict):
        if "target" not in payload:
            raise AKError("ON_BAR_BAD_RETURN",
                          f"on_bar 在 bar {t} 返回的 dict 缺少 target 键")
        raw = payload.get("target")
        raw_reason = payload.get("reason")
        reason = "" if raw_reason is None else str(raw_reason)
    elif isinstance(payload, (int, float)):
        raw, reason = payload, ""
    else:
        raise AKError("ON_BAR_BAD_RETURN",
                      f"on_bar 在 bar {t} 必须返回 float 或 {{'target': float, 'reason': str}}，"
                      f"收到 {type(payload).__name__}")

    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise AKError("ON_BAR_BAD_RETURN",
                      f"on_bar 在 bar {t} 返回的 target 不是数字: {raw!r}")
    target = float(raw)
    if not math.isfinite(target):
        raise AKError("ON_BAR_BAD_RETURN",
                      f"on_bar 在 bar {t} 返回的 target 不是有限数: {target!r}")
    clipped = False
    if target > 1.0:
        target, clipped = 1.0, True
    elif target < -1.0:
        target, clipped = -1.0, True
    return target, reason, clipped


def _call_init(strategy: Strategy, params: dict, ctx: EventContext) -> dict:
    if strategy.init is None:
        return {}
    try:
        state = strategy.init(dict(params), ctx)
    except AKError:
        raise
    except Exception as exc:  # noqa: BLE001 - 用户代码异常统一转引擎错误
        raise AKError("ENGINE_INTERNAL",
                      f"init 执行失败: {type(exc).__name__}: {exc}") from exc
    if not isinstance(state, dict):
        raise AKError("INIT_BAD_RETURN",
                      f"init 必须返回 dict 作为初始 state，收到 {type(state).__name__}")
    ensure_state_json(state)
    return state


def _call_on_bar(strategy: Strategy, state: dict, bar: dict, ctx: EventContext,
                 t: int) -> object:
    try:
        return strategy.on_bar(state, bar, ctx)
    except AKError:
        raise
    except Exception as exc:  # noqa: BLE001 - 用户代码异常统一转引擎错误
        raise AKError("ENGINE_INTERNAL",
                      f"on_bar 在 bar {t} 执行失败: {type(exc).__name__}: {exc}") from exc


def run_event(req: RunRequest, strategy: Strategy, engine: Engine) -> RunResult:
    req.validate()
    n = len(req.bars)
    eval_end = n - 1 if req.eval_end is None else int(req.eval_end)
    if eval_end < 0 or eval_end >= n:
        raise AKError("INPUT_INVALID", f"eval_end={eval_end} 超出 bars 范围 [0,{n - 1}]")
    warmup = max(int(strategy.warmup), 0)
    eval_start = warmup if req.eval_start is None else max(int(req.eval_start), warmup)
    if eval_start > eval_end:
        raise AKError("INPUT_INVALID",
                      f"评估窗口为空：eval_start={eval_start} > eval_end={eval_end}")

    view = [dict(b) for b in req.bars[:eval_end + 1]]
    for i, bar in enumerate(view):
        bar["index"] = i

    params = strategy.resolved(req.params)
    protection = merge_protection(strategy.protection, req.protection)

    matcher = MatchingEngine(
        initial_cash=req.initial_cash,
        fee_bps=req.fee_bps,
        slippage_bps=req.slippage_bps,
        rebalance_tolerance=req.rebalance_tolerance,
    )
    init_ctx = EventContext(view, -1, matcher, float(req.initial_cash), params, None)
    state = _call_init(strategy, params, init_ctx)

    eq_times: list[int] = []
    eq_values: list[float] = []
    warnings: list[str] = []
    pending: tuple[float, str] | None = None
    entry_index: int | None = None
    clipped = 0
    clamped = 0

    for i in range(eval_end + 1):
        deadline_check(req)
        bar = view[i]
        # 对账模式：eval_start 当根从空仓开始，不执行预热期留下的 pending
        if req.start_flat and i == eval_start:
            pending = None
        prev_pos = matcher.pos
        if pending is not None and i >= eval_start:
            target, reason = pending
            # 定仓用执行 bar 的开盘权益（与 signal 完全同口径）
            matcher.execute_target(bar, target, matcher.equity(float(bar["open"])), reason)
        matcher.check_protection(bar, protection)
        if matcher.pos == 0:
            entry_index = None
        elif prev_pos == 0 or _sign(prev_pos) != _sign(matcher.pos):
            entry_index = i
        close_equity = matcher.equity(float(bar["close"]))
        if i >= eval_start:
            eq_times.append(int(bar["timestamp"]))
            eq_values.append(close_equity)

        ctx = EventContext(view, i, matcher, close_equity, params, entry_index)
        raw = _call_on_bar(strategy, state, {k: bar[k] for k in _BAR_FIELDS}, ctx, i)
        target, reason, did_clip = normalize_event_return(raw, i)
        if did_clip:
            clipped += 1
        one, one_clamped = apply_direction([target], req.direction)
        clamped += one_clamped
        if i >= warmup:
            pending = (one[0], reason)
        else:
            pending = None

    last_bar = view[-1]
    if req.flatten:
        matcher.force_close(last_bar)
        if eq_values:
            eq_values[-1] = matcher.cash

    # 回测只跑完时校验一次；paper 的逐 bar 检查点留给 0.7.6
    ensure_state_json(state)

    if clipped:
        warnings.append(f"target_clipped={clipped}")
    if clamped:
        warnings.append(f"direction_clamped={clamped}")

    return finalize_result(
        req=req,
        strategy=strategy,
        engine=engine,
        view=view,
        fills=matcher.fills,
        trades=matcher.trades,
        eq_times=eq_times,
        eq_values=eq_values,
        warnings=warnings,
        protection=protection,
    )

