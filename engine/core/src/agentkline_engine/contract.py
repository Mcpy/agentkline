"""契约层：engine_api=1 / schema=1。

RunRequest 由后端或 CLI 构造；RunResult 是引擎唯一输出。
两端只透过 JSON 通信，所以这里只依赖标准库，且所有结构必须可 JSON 序列化。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .errors import AKError

ENGINE_API = 1
SCHEMA = 1

DIRECTIONS = ("long_only", "short_only", "both")

STATUSES = ("no_signals", "open_position_only", "completed_trades")

# 结果 assumptions 固定键（跨引擎逐字段对比）
DEFAULT_ASSUMPTIONS: dict[str, Any] = {
    "fill_rule": "next_open",
    "bar_close_policy": "closed_bars_only",
    "lot_policy": "continuous",
    "direction": "long_only",
    "shorting": "synthetic_no_borrow",
    "leverage": 1,
    "fee_bps": 5,
    "slippage_bps": 5,
    "funding_mode": "not_modeled",
    "calendar": "bar_clock",
    "corporate_actions": "not_modeled",
    "bars_per_year": 365.0,
    "annualization": "observed_bar_density",
    "protection_rule": "gap_open_then_intrabar_trigger",
    "intrabar_mode": "conservative",
}


@dataclass
class RunRequest:
    """一次回测请求。bars 按时间升序，元素为 timestamp/open/high/low/close/volume。"""

    engine: str = "builtin"
    bars: list[dict] = field(default_factory=list)
    strategy_source: str = ""
    params: dict = field(default_factory=dict)
    eval_start: int | None = None
    eval_end: int | None = None
    initial_cash: float = 10_000.0
    fee_bps: float = 5.0
    slippage_bps: float = 5.0
    direction: str = "long_only"
    protection: dict | None = None
    deadline: float | None = None  # time.monotonic() 绝对时间，协作式超时
    timeframe: str = ""
    symbol: str = ""
    rebalance_tolerance: float = 0.0001  # 防抖：目标数量相对漂移小于此比例不动

    def validate(self) -> None:
        if self.direction not in DIRECTIONS:
            raise AKError("INPUT_INVALID", f"direction 必须是 {DIRECTIONS} 之一，收到 {self.direction!r}")
        if not self.bars:
            raise AKError("BARS_INVALID", "bars 不能为空")
        try:
            cash = float(self.initial_cash)
        except (TypeError, ValueError):
            raise AKError("INPUT_INVALID", "initial_cash 必须是数字")
        if not (cash > 0):
            raise AKError("INPUT_INVALID", "initial_cash 必须 > 0")
        for name in ("fee_bps", "slippage_bps"):
            try:
                v = float(getattr(self, name))
            except (TypeError, ValueError):
                raise AKError("INPUT_INVALID", f"{name} 必须是数字")
            if v < 0:
                raise AKError("INPUT_INVALID", f"{name} 不能为负")
        if self.eval_start is not None and not isinstance(self.eval_start, int):
            raise AKError("INPUT_INVALID", "eval_start 必须是整数下标")
        if self.eval_end is not None and not isinstance(self.eval_end, int):
            raise AKError("INPUT_INVALID", "eval_end 必须是整数下标")
        if not self.strategy_source.strip():
            raise AKError("STRATEGY_SOURCE_EMPTY", "strategy_source 不能为空")

    def to_dict(self) -> dict:
        return {
            "api": ENGINE_API,
            "engine": self.engine,
            "bars": self.bars,
            "strategy_source": self.strategy_source,
            "params": self.params,
            "eval_start": self.eval_start,
            "eval_end": self.eval_end,
            "initial_cash": self.initial_cash,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "direction": self.direction,
            "protection": self.protection,
            "timeframe": self.timeframe,
            "symbol": self.symbol,
            "rebalance_tolerance": self.rebalance_tolerance,
        }


@dataclass
class RunResult:
    """引擎输出（schema=1）。字段名与主包 results.py 归一化后一致。"""

    engine: dict
    status: str
    bars: dict
    fills: list
    trades: list
    equity: dict  # {"times": [...], "values": [...]}
    stats: dict
    warnings: list
    assumptions: dict
    schema: int = SCHEMA

    def validate(self) -> None:
        if self.schema != SCHEMA:
            raise AKError("API_MISMATCH", f"结果 schema={self.schema}，期望 {SCHEMA}")
        if self.status not in STATUSES:
            raise AKError("ENGINE_INTERNAL", f"非法 status: {self.status!r}")
        eq = self.equity or {}
        if len(eq.get("times") or []) != len(eq.get("values") or []):
            raise AKError("ENGINE_INTERNAL", "equity.times/values 长度不一致")

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "engine": self.engine,
            "status": self.status,
            "bars": self.bars,
            "fills": self.fills,
            "trades": self.trades,
            "equity": self.equity,
            "stats": self.stats,
            "warnings": self.warnings,
            "assumptions": self.assumptions,
        }


@runtime_checkable
class Engine(Protocol):
    """引擎协议。实现方必须提供 id/version/api/caps 与 run()。"""

    id: str
    version: str
    api: int
    caps: dict
    assumptions: dict

    def run(self, req: RunRequest) -> RunResult:  # pragma: no cover - 协议
        ...


def engine_meta(engine: Engine) -> dict:
    """引擎自述（写进结果 engine 字段）。"""
    eid = getattr(engine, "id", "") or type(engine).__name__
    ver = str(getattr(engine, "version", "") or "")
    api = int(getattr(engine, "api", 0) or 0)
    caps = dict(getattr(engine, "caps", {}) or {})
    assumptions = dict(getattr(engine, "assumptions", {}) or {})
    return {"id": eid, "version": ver, "api": api, "caps": caps, "assumptions": assumptions}
