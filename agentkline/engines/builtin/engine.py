"""内置 signal 引擎。

口径：close 确认、next-open 成交、1x、连续数量、5bp 费用 + 5bp 滑点、
观测密度年化、合成空头（无借券/资金费）、末根强平。
"""
from __future__ import annotations

from agentkline_engine.contract import DEFAULT_ASSUMPTIONS, ENGINE_API, RunRequest, RunResult
from agentkline_engine.drivers.signal import run_signal
from agentkline_engine.loader import load_strategy

try:  # 主包版本即引擎版本
    from importlib.metadata import version as _pkg_version
    _VERSION = _pkg_version("agentkline")
except Exception:  # pragma: no cover - 未安装时直接跑源码
    _VERSION = "0.6.1"


class BuiltinEngine:
    id = "builtin"
    version = _VERSION
    api = ENGINE_API
    caps = {
        "signal": True,
        "event": False,
        "short": True,
        "leverage": False,
        "multi_symbol": False,
        "protection": True,
    }
    assumptions = dict(DEFAULT_ASSUMPTIONS)

    def run(self, req: RunRequest) -> RunResult:
        strategy = load_strategy(req.strategy_source)
        return run_signal(req, strategy, self)
