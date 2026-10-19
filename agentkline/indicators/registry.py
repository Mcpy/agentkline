"""指标注册表：type → compute(params, bars)。

每个子模块暴露 STUDIES = {type: fn}；fn 返回 {"lines": [...], "levels": [...], ...}。
"""
from __future__ import annotations

from . import averages, bands, oscillators, trend, volatility, volume, overlay

MODULES = (averages, bands, oscillators, trend, volatility, volume, overlay)
STUDIES: dict = {}
for _m in MODULES:
    STUDIES.update(getattr(_m, "STUDIES", {}))


def run(study_type: str, params: dict | None, bars: list) -> dict:
    fn = STUDIES.get(study_type)
    if fn is None:
        return {"error": f"UNKNOWN_STUDY: {study_type}"}
    return fn(params or {}, bars)


def types() -> list:
    return sorted(STUDIES)
