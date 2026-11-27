"""signal 驱动：target 校验、方向过滤、次开盘成交、保护、强平、权益序列。"""
from __future__ import annotations

import math

from ..bars import normalize_bars
from ..contract import Engine, RunRequest, RunResult
from ..errors import AKError
from ..loader import Strategy, load_strategy
from ..matching import MatchingEngine
from .common import apply_direction, deadline_check, finalize_result, merge_protection

_CLIP_EPS = 1e-15


def normalize_targets(payload, n: int) -> tuple[list[float], list[str], list[str]]:
    """把策略返回值归一成 (targets, reasons, warnings)。"""
    warnings: list[str] = []
    if isinstance(payload, dict):
        raw = payload.get("target")
        raw_reason = payload.get("reason")
    elif isinstance(payload, (list, tuple)):
        raw, raw_reason = payload, None
    else:
        raise AKError("TARGET_INVALID", f"策略必须返回 dict{{'target': [...]}}，收到 {type(payload).__name__}")
    if not isinstance(raw, (list, tuple)):
        raise AKError("TARGET_INVALID", "target 必须是数组")
    if len(raw) != n:
        raise AKError("TARGET_LENGTH", f"target 长度 {len(raw)} 与 bars 长度 {n} 不一致")

    targets: list[float] = []
    clipped = 0
    for i, v in enumerate(raw):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise AKError("TARGET_INVALID", f"target[{i}] 不是数字: {v!r}")
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise AKError("TARGET_INVALID", f"target[{i}] 不是数字: {v!r}")
        if not math.isfinite(f):
            raise AKError("TARGET_NONFINITE", f"target[{i}] 不是有限数: {f!r}")
        if f > 1.0:
            f = 1.0
            clipped += 1
        elif f < -1.0:
            f = -1.0
            clipped += 1
        targets.append(f)
    if clipped:
        warnings.append(f"target_clipped={clipped}")

    reasons = [""] * n
    if isinstance(raw_reason, (list, tuple)):
        if len(raw_reason) != n:
            warnings.append("reason_length_mismatch")
        for i in range(min(n, len(raw_reason))):
            reasons[i] = str(raw_reason[i] or "")
    elif raw_reason is not None:
        warnings.append("reason_ignored")
    return targets, reasons, warnings


def run_signal(req: RunRequest, strategy: Strategy, engine: Engine) -> RunResult:
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
    # 策略只看到 OHLCV（timestamp/open/high/low/close/volume）；index 是引擎内部字段
    strategy_view = [{k: v for k, v in b.items() if k != "index"} for b in view]
    try:
        payload = strategy.main(params, strategy_view)
    except AKError:
        raise
    except Exception as exc:  # noqa: BLE001 - 用户代码异常统一转引擎错误
        raise AKError("ENGINE_INTERNAL",
                      f"策略执行失败: {type(exc).__name__}: {exc}") from exc

    targets, reasons, warnings = normalize_targets(payload, len(view))
    targets, clamped = apply_direction(targets, req.direction)
    if clamped:
        warnings.append(f"direction_clamped={clamped}")
    protection = merge_protection(strategy.protection, req.protection)

    matcher = MatchingEngine(
        initial_cash=req.initial_cash,
        fee_bps=req.fee_bps,
        slippage_bps=req.slippage_bps,
        rebalance_tolerance=req.rebalance_tolerance,
    )
    eq_times: list[int] = []
    eq_values: list[float] = []
    pending: tuple[float, str] | None = None

    for i in range(eval_end + 1):
        deadline_check(req)
        bar = view[i]
        # 对账模式：eval_start 当根从 paper 的空仓开始，不执行预热期留下的 pending
        if req.start_flat and i == eval_start:
            pending = None
        if pending is not None and i >= eval_start:
            target, reason = pending
            # 定仓用执行 bar 的开盘权益（与 Vibe 一致：用能成交的价格重估）
            matcher.execute_target(bar, target, matcher.equity(float(bar["open"])), reason)
        matcher.check_protection(bar, protection)
        close_equity = matcher.equity(float(bar["close"]))
        if i >= eval_start:
            eq_times.append(int(bar["timestamp"]))
            eq_values.append(close_equity)
        if i >= warmup:
            pending = (targets[i], reasons[i])
        else:
            pending = None

    last_bar = view[-1]
    if req.flatten:
        matcher.force_close(last_bar)
        if eq_values:
            eq_values[-1] = matcher.cash

    fills = matcher.fills
    trades = matcher.trades
    return finalize_result(
        req=req,
        strategy=strategy,
        engine=engine,
        view=view,
        fills=fills,
        trades=trades,
        eq_times=eq_times,
        eq_values=eq_values,
        warnings=warnings,
        protection=protection,
    )


def signal_last(bars: list[dict], strategy_source: str, params: dict | None = None,
                direction: str = "long_only", timeframe: str = "") -> dict:
    """只求“最后一根 bar 收盘后的目标仓位”，不撮合、不记权益。

    paper 执行器用它把策略求值留在引擎子进程里；输入窗口最后一根必须是
    已确认的决策 bar P，输出 target 就是下一根 B 开盘要执行的目标。
    """
    if direction not in ("long_only", "short_only", "both"):
        raise AKError("INPUT_INVALID", f"direction 必须为 long_only/short_only/both，收到 {direction!r}")
    view, bars_warnings = normalize_bars(bars, source="paper bars")
    if not view:
        raise AKError("BARS_INVALID", "paper bars 不能为空")
    strategy = load_strategy(strategy_source)
    if strategy.mode != "signal":
        raise AKError("MODE_MISMATCH",
                      f"signal 子命令只支持 STRATEGY_MODE=\"signal\"，收到 {strategy.mode!r}")
    warmup = max(int(strategy.warmup or 0), 0)
    if len(view) <= warmup:
        raise AKError("WARMUP_SHORT",
                      f"paper 窗口只有 {len(view)} 根，不够策略预热 WARMUP={warmup}")
    strategy_view = [{k: v for k, v in b.items() if k != "index"} for b in view]
    try:
        payload = strategy.main(strategy.resolved(params or {}), strategy_view)
    except AKError:
        raise
    except Exception as exc:  # noqa: BLE001 - 用户代码异常统一转引擎错误
        raise AKError("ENGINE_INTERNAL",
                      f"策略执行失败: {type(exc).__name__}: {exc}") from exc

    targets, reasons, warnings = normalize_targets(payload, len(view))
    targets, clamped = apply_direction(targets, direction)
    if clamped:
        warnings.append(f"direction_clamped={clamped}")
    return {
        "status": "ok",
        "target": float(targets[-1]),
        "reason": str(reasons[-1] or "") if reasons else "",
        "warnings": bars_warnings + warnings,
        "warmup": warmup,
        "bars": len(view),
        "timeframe": timeframe,
        "protection": merge_protection(strategy.protection, None),
        "source_sha256": strategy.source_sha256,
    }
