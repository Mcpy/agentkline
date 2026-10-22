"""结果层：把撮合输出装配成 schema=1 的 RunResult。"""
from __future__ import annotations

from .contract import Engine, RunResult, SCHEMA, engine_meta


def build_result(*, engine: Engine, status: str, bars: dict, fills: list, trades: list,
                 times: list, values: list, stats: dict, warnings: list,
                 assumptions: dict) -> RunResult:
    meta = engine_meta(engine)
    # 引擎级 assumptions 作为兜底，驱动算出的口径优先
    merged = dict(meta.get("assumptions") or {})
    merged.update(assumptions or {})
    meta["assumptions"] = merged
    res = RunResult(
        schema=SCHEMA,
        engine=meta,
        status=status,
        bars=bars,
        fills=list(fills),
        trades=list(trades),
        equity={"times": list(times), "values": list(values)},
        stats=stats,
        warnings=list(warnings),
        assumptions=merged,
    )
    res.validate()
    return res
