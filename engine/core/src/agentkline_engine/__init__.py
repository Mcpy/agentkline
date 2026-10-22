"""AgentKline 引擎框架（agentkline-engine-core）。

只依赖标准库：契约、撮合核、统计口径、CLI。
内置引擎在主包 `agentkline.engines.builtin`；第三方引擎按 entry point 注册。
"""
from __future__ import annotations

from .bars import load_bars, normalize_bars
from .contract import ENGINE_API, SCHEMA, Engine, RunRequest, RunResult
from .errors import AKError
from .loader import check_source, describe_source, load_strategy, load_strategy_file
from .matching import MatchingEngine
from .metrics import compute_stats_full
from .registry import discover, get_engine, list_engines
from .result import build_result

__version__ = "0.1.0"

__all__ = [
    "AKError", "ENGINE_API", "SCHEMA", "Engine", "RunRequest", "RunResult",
    "MatchingEngine", "build_result", "check_source", "compute_stats_full",
    "describe_source", "discover", "get_engine", "list_engines", "load_bars",
    "load_strategy", "load_strategy_file", "normalize_bars", "__version__",
]
