"""撮合核：次开盘、费用/滑点、保护、反手、部分仓、强平（G1 E5–E9）。"""
from __future__ import annotations

import unittest

import _util  # noqa: F401  - 把仓库根加入 sys.path

from agentkline_engine.matching import MatchingEngine


def bar(i=0, o=100.0, h=None, l=None, c=None, ts=None):
    c = o if c is None else c
    return {
        "timestamp": ts if ts is not None else 1_600_000_000_000 + i * 86_400_000,
        "index": i,
        "open": o,
        "high": o if h is None else h,
        "low": o if l is None else l,
        "close": c,
        "volume": 1.0,
    }


class NextOpenTest(unittest.TestCase):
    def test_fill_at_next_open_with_gap(self):
        eng = MatchingEngine(1000, fee_bps=0, slippage_bps=10)
        b1 = bar(1, o=120.0, c=125.0, ts=1_600_086_400_000)
        fills = eng.execute_target(b1, 1.0, 1000.0, "sig")
        self.assertEqual(len(fills), 1)
        f = fills[0]
        self.assertEqual(f["time"], 1_600_086_400_000)
        self.assertAlmostEqual(f["price"], 120.0 * 1.001, places=12)
        # 数量按含滑点成交价折算，否则占用资金会多出一个滑点位
        self.assertAlmostEqual(f["signed_qty"], 1000.0 / (120.0 * 1.001), places=12)


class CostTest(unittest.TestCase):
    def test_hand_calculated_fill(self):
        eng = MatchingEngine(1000, fee_bps=10, slippage_bps=10)
        b1 = bar(1, o=100.0, c=110.0)
        fills = eng.execute_target(b1, 0.5, 1000.0, "sig")
        f = fills[0]
        self.assertAlmostEqual(f["price"], 100.1, places=12)
        # 目标名义 500（E*target）→ 数量 500/成交价；成本恰好 500 + 0.5 手续费
        self.assertAlmostEqual(f["notional"], 500.0, places=12)
        self.assertAlmostEqual(f["fee"], 0.5, places=12)
        self.assertAlmostEqual(f["signed_qty"], 500.0 / 100.1, places=12)
        self.assertAlmostEqual(eng.cash, 499.5, places=12)
        self.assertAlmostEqual(eng.equity(110.0), 499.5 + (500.0 / 100.1) * 110.0, places=12)

    def test_sell_side_slippage_and_fee(self):
        eng = MatchingEngine(1000, fee_bps=10, slippage_bps=10)
        f1 = eng.execute_target(bar(1, o=100.0), 1.0, 1000.0)[0]
        qty = f1["signed_qty"]
        cash_after_buy = eng.cash
        fills = eng.execute_target(bar(2, o=200.0), 0.0, 0.0, "")
        f = fills[0]
        self.assertAlmostEqual(f["price"], 200.0 * 0.999, places=12)
        expected_fee = qty * 200.0 * 0.999 * 0.001
        self.assertAlmostEqual(f["fee"], expected_fee, places=12)
        self.assertAlmostEqual(eng.cash, cash_after_buy + qty * 200.0 * 0.999 - expected_fee,
                               places=12)
        self.assertEqual(eng.pos, 0.0)

    def test_min_notional_debounce(self):
        eng = MatchingEngine(1000, fee_bps=0, slippage_bps=0)
        eng.execute_target(bar(1, o=100.0), 1.0, 1000.0)
        # 目标从 1.0 变到 0.9999：差额 0.1 美元，低于净值 1bp（0.1 美元）→ 不动
        fills = eng.execute_target(bar(2, o=100.0), 0.99995, 1000.0)
        self.assertEqual(fills, [])


class ProtectionTest(unittest.TestCase):
    def _long(self):
        eng = MatchingEngine(1000, fee_bps=0, slippage_bps=0)
        eng.execute_target(bar(0, o=100.0), 1.0, 1000.0)
        self.assertAlmostEqual(eng.avg_price, 100.0)
        return eng

    def test_gap_through_stop_uses_open(self):
        eng = self._long()
        fills = eng.check_protection(bar(1, o=90.0, h=95.0, l=89.0),
                                     {"stop_loss_pct": 0.05})
        self.assertEqual(len(fills), 1)
        self.assertAlmostEqual(fills[0]["price"], 90.0)
        self.assertEqual(fills[0]["reason"], "stop_loss")
        self.assertEqual(eng.pos, 0.0)

    def test_intrabar_stop_uses_trigger(self):
        eng = self._long()
        fills = eng.check_protection(bar(1, o=100.0, h=101.0, l=94.0),
                                     {"stop_loss_pct": 0.05})
        self.assertAlmostEqual(fills[0]["price"], 95.0)
        self.assertEqual(fills[0]["reason"], "stop_loss")

    def test_stop_wins_over_target_same_bar(self):
        eng = self._long()
        fills = eng.check_protection(bar(1, o=100.0, h=112.0, l=94.0),
                                     {"stop_loss_pct": 0.05, "take_profit_pct": 0.10})
        self.assertAlmostEqual(fills[0]["price"], 95.0)
        self.assertEqual(fills[0]["reason"], "stop_loss")

    def test_take_profit_intrabar(self):
        eng = self._long()
        fills = eng.check_protection(bar(1, o=101.0, h=112.0, l=100.0),
                                     {"take_profit_pct": 0.10})
        self.assertAlmostEqual(fills[0]["price"], 110.0)
        self.assertEqual(fills[0]["reason"], "take_profit")

    def test_short_stop_gap(self):
        eng = MatchingEngine(1000, fee_bps=0, slippage_bps=0)
        eng.execute_target(bar(0, o=100.0), -1.0, 1000.0)
        self.assertAlmostEqual(eng.avg_price, 100.0)
        fills = eng.check_protection(bar(1, o=106.0, h=107.0, l=105.0),
                                     {"stop_loss_pct": 0.05})
        self.assertAlmostEqual(fills[0]["price"], 106.0)
        self.assertEqual(fills[0]["reason"], "stop_loss")
        self.assertEqual(eng.pos, 0.0)

    def test_short_take_profit_intrabar(self):
        eng = MatchingEngine(1000, fee_bps=0, slippage_bps=0)
        eng.execute_target(bar(0, o=100.0), -1.0, 1000.0)
        fills = eng.check_protection(bar(1, o=99.0, h=100.0, l=89.0),
                                     {"take_profit_pct": 0.10})
        self.assertAlmostEqual(fills[0]["price"], 90.0)
        self.assertEqual(fills[0]["reason"], "take_profit")


class FlipAndPartialTest(unittest.TestCase):
    def test_flip_splits_into_two_fills(self):
        eng = MatchingEngine(1000, fee_bps=0, slippage_bps=0)
        eng.execute_target(bar(0, o=100.0), 1.0, 1000.0)
        fills = eng.execute_target(bar(1, o=100.0), -1.0, 1000.0)
        self.assertEqual(len(fills), 2)
        self.assertEqual([f["action"] for f in fills], ["sell", "sell"])
        self.assertAlmostEqual(fills[0]["signed_qty"], -10.0)
        self.assertAlmostEqual(fills[1]["signed_qty"], -10.0)
        self.assertEqual(len(eng.trades), 1)
        self.assertEqual(eng.trades[0]["side"], "long")
        self.assertAlmostEqual(eng.trades[0]["pnl"], 0.0)
        self.assertEqual(eng.pos, -10.0)

    def test_partial_reduce_then_close(self):
        eng = MatchingEngine(1000, fee_bps=0, slippage_bps=0)
        eng.execute_target(bar(0, o=100.0), 1.0, 1000.0)
        eq1 = eng.equity(100.0)
        f1 = eng.execute_target(bar(1, o=110.0), 0.5, eq1)
        self.assertEqual(len(f1), 1)
        self.assertAlmostEqual(f1[0]["signed_qty"], -(10.0 - 0.5 * 1000.0 / 110.0))
        self.assertEqual(len(eng.trades), 0)
        eq2 = eng.equity(110.0)
        f2 = eng.execute_target(bar(2, o=120.0), 0.0, eq2)
        self.assertEqual(len(f2), 1)
        self.assertEqual(len(eng.trades), 1)
        t = eng.trades[0]
        self.assertAlmostEqual(t["size"], 10.0, places=12)
        self.assertAlmostEqual(t["entry_price"], 100.0, places=12)
        self.assertAlmostEqual(t["holding_bars"], 2)
        # 两次减仓的加权卖出均价
        q1 = 10.0 - 0.5 * 1000.0 / 110.0
        q2 = 0.5 * 1000.0 / 110.0
        self.assertAlmostEqual(t["exit_price"], (q1 * 110.0 + q2 * 120.0) / (q1 + q2), places=12)
        self.assertAlmostEqual(t["gross_pnl"], (110.0 - 100.0) * q1 + (120.0 - 100.0) * q2, places=12)
        self.assertAlmostEqual(eng.pos, 0.0)
        self.assertEqual(eng.cash, 1000.0 + t["gross_pnl"])


class ReduceThenAddTest(unittest.TestCase):
    def test_entry_price_after_reduce_then_add(self):
        eng = MatchingEngine(1000, fee_bps=0, slippage_bps=0)
        eng.execute_target(bar(0, o=100.0), 1.0, 1000.0)        # 10 @ 100
        eng.execute_target(bar(1, o=110.0), 0.5, 1000.0)        # 卖 5 @ 110
        self.assertAlmostEqual(eng.avg_price, 100.0)
        eq = eng.equity(110.0)                                  # 1100
        eng.execute_target(bar(2, o=105.0), 1050.0 / eq, eq)    # 目标名义 1050 @ 105 → 10 股
        q_keep = 0.5 * 1000.0 / 110.0                            # 减仓后剩的股数
        q_add = 10.0 - q_keep
        avg = (q_keep * 100.0 + q_add * 105.0) / 10.0
        gross = (110.0 - 100.0) * q_add + (130.0 - avg) * 10.0
        self.assertAlmostEqual(eng.pos, 10.0, places=12)
        self.assertAlmostEqual(eng.avg_price, avg, places=12)
        eng.force_close(bar(3, o=130.0, c=130.0))
        t = eng.trades[0]
        # 若用累加的 entry_notional/entry_qty 会得到 ~71.5，必须用当前持仓成本
        self.assertAlmostEqual(t["entry_price"], avg, places=12)
        self.assertAlmostEqual(t["size"], 10.0, places=12)
        self.assertAlmostEqual(t["gross_pnl"], gross, places=12)
        self.assertAlmostEqual(eng.cash, 1000.0 + gross, places=12)
        self.assertAlmostEqual(t["pnl"], gross, places=12)


class ForceCloseTest(unittest.TestCase):
    def test_end_of_backtest(self):
        eng = MatchingEngine(1000, fee_bps=10, slippage_bps=10)
        eng.execute_target(bar(0, o=100.0), 1.0, 1000.0)
        last = bar(1, o=130.0, c=130.0)
        fills = eng.force_close(last)
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0]["reason"], "end_of_backtest")
        self.assertAlmostEqual(fills[0]["price"], 130.0 * 0.999, places=12)
        self.assertEqual(eng.pos, 0.0)
        self.assertAlmostEqual(eng.equity(130.0), eng.cash)
        self.assertEqual(len(eng.trades), 1)
        self.assertEqual(eng.trades[0]["exit_reason"], "end_of_backtest")

    def test_force_close_noop_when_flat(self):
        eng = MatchingEngine(1000)
        self.assertEqual(eng.force_close(bar(0)), [])


if __name__ == "__main__":
    unittest.main()
