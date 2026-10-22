"""signal 驱动：target 校验、方向过滤、次开盘成交、保护、强平、权益序列。"""
from __future__ import annotations

import math
import time

from ..bars import bars_meta
from ..contract import DEFAULT_ASSUMPTIONS, Engine, RunRequest, RunResult
from ..errors import AKError, RunTimeout
from ..loader import Strategy
from ..matching import MatchingEngine
from ..metrics import compute_stats_full, observed_bars_per_year
from ..result import build_result

_PROTECTION_KEYS = ("stop_loss_pct", "take_profit_pct")
_CLIP_EPS = 1e-15


def _deadline_check(req: RunRequest) -> None:
    if req.deadline is not None and time.monotonic() > req.deadline:
        raise RunTimeout("运行超过 deadline")


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


def apply_direction(targets: list[float], direction: str) -> tuple[list[float], int]:
    """方向过滤：long_only 裁掉空头，short_only 裁掉多头，both 不动。"""
    if direction == "both":
        return list(targets), 0
    out: list[float] = []
    clamped = 0
    for t in targets:
        if direction == "long_only" and t < 0:
            out.append(0.0)
            clamped += 1
        elif direction == "short_only" and t > 0:
            out.append(0.0)
            clamped += 1
        else:
            out.append(t)
    return out, clamped


def merge_protection(declared: dict | None, override: dict | None) -> dict:
    out = dict(declared or {})
    if override:
        if not isinstance(override, dict):
            raise AKError("PROTECTION_INVALID", "protection 必须是 dict")
        for key, val in override.items():
            if key not in _PROTECTION_KEYS:
                raise AKError("PROTECTION_UNKNOWN_KEY", f"未知保护键: {key!r}")
            try:
                f = float(val)
            except (TypeError, ValueError):
                raise AKError("PROTECTION_INVALID", f"PROTECTION[{key!r}] 必须是数字")
            if not (0 < f < 1):
                raise AKError("PROTECTION_INVALID", f"PROTECTION[{key!r}] 必须在 (0,1) 内")
            out[key] = f
    for key, val in list(out.items()):
        if key not in _PROTECTION_KEYS:
            raise AKError("PROTECTION_UNKNOWN_KEY", f"未知保护键: {key!r}")
        try:
            f = float(val)
        except (TypeError, ValueError):
            raise AKError("PROTECTION_INVALID", f"PROTECTION[{key!r}] 必须是数字")
        if not (0 < f < 1):
            raise AKError("PROTECTION_INVALID", f"PROTECTION[{key!r}] 必须在 (0,1) 内")
        out[key] = f
    return out


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
        _deadline_check(req)
        bar = view[i]
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
    matcher.force_close(last_bar)
    if eq_values:
        eq_values[-1] = matcher.cash

    fills = matcher.fills
    trades = matcher.trades
    status = ("no_signals" if not fills
              else "open_position_only" if not trades
              else "completed_trades")

    bpy = strategy.bars_per_year
    annualization = "declared"
    if bpy is None:
        bpy = observed_bars_per_year(eq_times)
        annualization = "observed_bar_density"
    stats = compute_stats_full(eq_times, eq_values, trades,
                               float(req.initial_cash), int(round(bpy)),
                               fills=fills)
    # total_fees 以 fills 为准：未强平的插件引擎也能算对
    stats["total_fees"] = sum(float(f.get("fee") or 0.0) for f in fills)

    assumptions = dict(DEFAULT_ASSUMPTIONS)
    assumptions.update({
        "direction": req.direction,
        "fee_bps": req.fee_bps,
        "slippage_bps": req.slippage_bps,
        "bars_per_year": round(float(bpy), 4),
        "annualization": annualization,
    })
    if not protection:
        assumptions["protection_rule"] = "none"

    return build_result(
        engine=engine,
        status=status,
        bars=bars_meta(view, req.timeframe),
        fills=fills,
        trades=trades,
        times=eq_times,
        values=eq_values,
        stats=stats,
        warnings=warnings,
        assumptions=assumptions,
    )
