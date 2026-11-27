"""内置引擎：signal / event 双范式，共用同一撮合核与结果口径。

口径：close 确认、next-open 成交、1x、连续数量、5bp 费用 + 5bp 滑点、
观测密度年化、合成空头（无借券/资金费）、末根强平。
"""
from __future__ import annotations

from agentkline_engine.contract import DEFAULT_ASSUMPTIONS, ENGINE_API, RunRequest, RunResult
from agentkline_engine.drivers.event import run_event
from agentkline_engine.drivers.signal import run_signal
from agentkline_engine.errors import AKError
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
        "event": True,
        "short": True,
        "leverage": False,
        "multi_symbol": False,
        "protection": True,
    }
    assumptions = dict(DEFAULT_ASSUMPTIONS)

    def run(self, req: RunRequest) -> RunResult:
        strategy = load_strategy(req.strategy_source)
        # 请求显式给了 mode 就必须与策略声明一致；没给则按策略声明分派
        if req.mode is not None and req.mode != strategy.mode:
            raise AKError("MODE_MISMATCH",
                          f"请求 mode={req.mode!r} 与策略 STRATEGY_MODE={strategy.mode!r} 不一致")
        if strategy.mode == "event":
            return run_event(req, strategy, self)
        return run_signal(req, strategy, self)
