"""撮合核：签名仓位、加权均价、费用、滑点、保护、强平、回合账务。

只处理"一个标的 + 连续数量 + 1x"；不碰策略、不碰数据来源。
时间线由驱动负责：bar t 收盘给目标，t+1 开盘执行，盘中查保护，收盘记权益。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .errors import AKError

_EPS = 1e-12


@dataclass
class _Trade:
    side: str
    entry_index: int
    entry_time: int
    entry_notional: float = 0.0
    entry_qty: float = 0.0
    exit_notional: float = 0.0
    exit_qty: float = 0.0
    fee: float = 0.0
    gross: float = 0.0
    max_qty: float = 0.0
    entry_reason: str = ""


def _sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


class MatchingEngine:
    """单标的撮合与账务。"""

    def __init__(self, initial_cash: float, fee_bps: float = 5.0,
                 slippage_bps: float = 5.0, rebalance_tolerance: float = 0.0001):
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.fee_rate = float(fee_bps) / 10_000.0
        self.slip_rate = float(slippage_bps) / 10_000.0
        self.tolerance = float(rebalance_tolerance)
        self.pos = 0.0
        self.avg_price = 0.0
        self.fills: list[dict] = []
        self.trades: list[dict] = []
        self._trade: _Trade | None = None

    # ---------------------------- 查询 ----------------------------

    def equity(self, price: float) -> float:
        return self.cash + self.pos * price

    def _sizes(self, target: float, price: float, equity: float) -> tuple[float, float]:
        """返回 (同向价下的目标数量, 反向价下的目标数量)，均为正数。

        与 Vibe 同口径：目标名义按权益算，数量分别按买价/卖价折算；两个方向
        夹住当前仓位时不交易（把小于一个滑点带宽的漂移当作噪声）。
        """
        e = max(float(equity), 0.0)
        if target > 0:
            p_same = price * (1 + self.slip_rate)
            p_opp = price * (1 - self.slip_rate)
        else:
            p_same = price * (1 - self.slip_rate)
            p_opp = price * (1 + self.slip_rate)
        return (e * abs(target) / p_same, e * abs(target) / p_opp)

    def _available(self, target: float, equity: float) -> float:
        """可用于本次增量买入/卖空的资金（1x 保证金口径）。"""
        if target > 0:
            return max(equity, 0.0) if self.pos < 0 else self.cash
        if self.pos > 0:
            return max(equity, 0.0)
        return self.cash - 2.0 * abs(self.pos) * self.avg_price

    def execute_target(self, bar: dict, target: float, signal_equity: float,
                       reason: str = "") -> list[dict]:
        """在 bar 开盘按 target 调仓。返回本次 fills（可能 0/1/2 笔）。

        规则与 Vibe `position_adjustment="rebalance"` 对齐：
          1. 反手先平仓（释放保证金），再按平仓后的可用资金开新仓；
          2. 目标数量分别按买价/卖价折算，两者夹住当前仓位就不动；
          3. 相对漂移不超过 `rebalance_tolerance` 不动；
          4. 增量受可用资金约束（含手续费），超出则按比例缩量。
        """
        price = float(bar["open"])
        if price <= 0:
            raise AKError("BARS_INVALID", "开盘价必须 > 0")

        if target == 0:
            if self.pos == 0:
                return []
            return self._fill(bar, -self.pos, price, reason or "target_flat")

        tag = reason or "signal"
        fills: list[dict] = []
        if self.pos != 0 and _sign(target) != _sign(self.pos):
            fills += self._fill(bar, -self.pos, price, "flip")

        e = max(float(signal_equity), 0.0)
        size_same, size_opp = self._sizes(target, price, e)
        mag = abs(self.pos)

        # 漂移带：目标数量与当前数量相对差小于阈值就当噪声
        ref_size = e * abs(target) / price
        if self.tolerance > 0 and mag > 0 and abs(mag - ref_size) <= self.tolerance * abs(ref_size):
            return fills

        increase = size_same > mag + 1e-9
        reduction = size_opp < mag - 1e-9
        if increase == reduction:
            return fills

        p_same = price * (1 + self.slip_rate) if target > 0 else price * (1 - self.slip_rate)
        if increase:
            delta = size_same - mag
            avail = max(self._available(target, e), 0.0)
            cost = delta * p_same * (1.0 + self.fee_rate)
            if cost > avail and cost > 0:
                delta *= avail / cost
        else:
            delta = size_opp - mag  # 负数
        if abs(delta) <= 1e-12:
            return fills
        signed = delta if target > 0 else -delta
        fills += self._fill(bar, signed, price, tag)
        return fills

    def check_protection(self, bar: dict, protection: dict | None) -> list[dict]:
        """盘中止损/止盈。同一根先止损后止盈（conservative）。"""
        if self.pos == 0 or not protection:
            return []
        sl = protection.get("stop_loss_pct")
        tp = protection.get("take_profit_pct")
        if not sl and not tp:
            return []
        avg = self.avg_price
        o, h, l = float(bar["open"]), float(bar["high"]), float(bar["low"])
        if self.pos > 0:
            stop = avg * (1 - sl) if sl else None
            take = avg * (1 + tp) if tp else None
            if stop is not None and o <= stop:
                return self._exit(bar, o, "stop_loss")
            if take is not None and o >= take:
                return self._exit(bar, o, "take_profit")
            if stop is not None and l <= stop:
                return self._exit(bar, stop, "stop_loss")
            if take is not None and h >= take:
                return self._exit(bar, take, "take_profit")
        else:
            stop = avg * (1 + sl) if sl else None
            take = avg * (1 - tp) if tp else None
            if stop is not None and o >= stop:
                return self._exit(bar, o, "stop_loss")
            if take is not None and o <= take:
                return self._exit(bar, o, "take_profit")
            if stop is not None and h >= stop:
                return self._exit(bar, stop, "stop_loss")
            if take is not None and l <= take:
                return self._exit(bar, take, "take_profit")
        return []

    def force_close(self, bar: dict, reason: str = "end_of_backtest") -> list[dict]:
        if self.pos == 0:
            return []
        return self._fill(bar, -self.pos, float(bar["close"]), reason)

    # ---------------------------- 账务 ----------------------------

    def _exit(self, bar: dict, price: float, reason: str) -> list[dict]:
        return self._fill(bar, -self.pos, price, reason, slippage=False)

    def _fill(self, bar: dict, qty: float, price: float, reason: str,
              slippage: bool = True) -> list[dict]:
        if abs(qty) < _EPS:
            return []
        old = self.pos
        # 反手：拆成"先平后开"两笔
        if old != 0 and _sign(old) != _sign(qty) and abs(qty) > abs(old):
            return (self._fill(bar, -old, price, "flip", slippage)
                    + self._fill(bar, qty + old, price, reason, slippage))

        exec_price = price * (1 + self.slip_rate) if qty > 0 else price * (1 - self.slip_rate)
        if not slippage:
            exec_price = price
        if exec_price <= 0:
            raise AKError("BARS_INVALID", "成交价必须 > 0")
        fee = abs(qty) * exec_price * self.fee_rate
        self.cash -= qty * exec_price
        self.cash -= fee

        fid = f"f{len(self.fills) + 1}"
        fill = {
            "id": fid,
            "time": int(bar["timestamp"]),
            "index": int(bar.get("index", -1)),
            "action": "buy" if qty > 0 else "sell",
            "signed_qty": qty,
            "price": exec_price,
            "notional": abs(qty) * exec_price,
            "fee": fee,
            "reason": reason,
        }
        self.fills.append(fill)

        new = old + qty
        if old == 0:
            self._open_trade(bar, qty, exec_price, reason, fee)
            self.avg_price = exec_price
        elif _sign(old) == _sign(new) and abs(new) > abs(old):
            # 同向加仓：更新加权均价
            self.avg_price = ((self.avg_price * abs(old) + exec_price * abs(qty))
                              / abs(new))
            t = self._trade
            t.entry_notional += abs(qty) * exec_price
            t.entry_qty += abs(qty)
            t.max_qty = max(t.max_qty, abs(new))
            t.fee += fee
        elif _sign(old) == _sign(new) or new == 0:
            # 同向减仓或平仓：按均价实现盈亏
            closed = min(abs(qty), abs(old))
            self._trade.gross += (exec_price - self.avg_price) * closed * _sign(old)
            self._trade.exit_notional += closed * exec_price
            self._trade.exit_qty += closed
            self._trade.fee += fee
            if abs(new) < _EPS:
                new = 0.0
                self._close_trade(bar, reason)
                self.avg_price = 0.0
        else:  # pragma: no cover - 反手已在上方拆分
            raise AKError("ENGINE_INTERNAL", "撮合内部错误：跨零成交量未拆分")

        self.pos = new
        return [fill]

    def _open_trade(self, bar: dict, qty: float, price: float, reason: str, fee: float) -> None:
        if self._trade is not None:
            raise AKError("ENGINE_INTERNAL", "已有未平仓回合，不能重复开仓")
        self._trade = _Trade(
            side="long" if qty > 0 else "short",
            entry_index=int(bar.get("index", -1)),
            entry_time=int(bar["timestamp"]),
            entry_notional=abs(qty) * price,
            entry_qty=abs(qty),
            fee=fee,
            max_qty=abs(qty),
            entry_reason=reason or "",
        )

    def _close_trade(self, bar: dict, reason: str) -> None:
        t = self._trade
        if t is None:  # pragma: no cover
            raise AKError("ENGINE_INTERNAL", "没有未平仓回合可关闭")
        # 均价以引擎当前持仓成本为准：减仓后再加仓时，
        # entry_notional/entry_qty 会把已平掉的部分算进去，不能直接用。
        entry_price = self.avg_price or (t.entry_notional / t.entry_qty if t.entry_qty else 0.0)
        exit_price = t.exit_notional / t.exit_qty if t.exit_qty else entry_price
        size = t.max_qty
        notional = entry_price * size
        pnl = t.gross - t.fee
        exit_index = int(bar.get("index", -1))
        self.trades.append({
            "id": f"t{len(self.trades) + 1}",
            "side": t.side,
            "entry_time": t.entry_time,
            "exit_time": int(bar["timestamp"]),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "size": size,
            "notional": notional,
            "gross_pnl": t.gross,
            "fee": t.fee,
            "pnl": pnl,
            "pnl_pct": (pnl / notional) if notional else 0.0,
            "entry_reason": t.entry_reason,
            "exit_reason": reason or "",
            "holding_bars": max(0, exit_index - t.entry_index),
        })
        self._trade = None
