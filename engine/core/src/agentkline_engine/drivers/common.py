"""驱动共用：方向过滤、保护合并、超时检查、结果装配。

signal / event 两条路径共用同一撮合核与同一结果口径，凡是不涉及“策略怎么产出
target”的部分都放这里，避免两套账务口径漂移。
"""
from __future__ import annotations

import time

from ..bars import bars_meta
from ..contract import DEFAULT_ASSUMPTIONS, Engine, RunRequest, RunResult
from ..errors import AKError, RunTimeout
from ..loader import Strategy
from ..metrics import compute_stats_full, observed_bars_per_year
from ..result import build_result

_PROTECTION_KEYS = ("stop_loss_pct", "take_profit_pct")


def deadline_check(req: RunRequest) -> None:
    if req.deadline is not None and time.monotonic() > req.deadline:
        raise RunTimeout("运行超过 deadline")


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


def finalize_result(*, req: RunRequest, strategy: Strategy, engine: Engine,
                    view: list[dict], fills: list[dict], trades: list[dict],
                    eq_times: list[int], eq_values: list[float],
                    warnings: list[str], protection: dict) -> RunResult:
    """两种范式共用的结果装配：状态、年化、统计、assumptions。"""
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
        mode=strategy.mode,
    )
