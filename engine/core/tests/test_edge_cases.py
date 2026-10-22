"""刁钻场景与账务不变量（内置引擎最容易出错的地方）。

覆盖：单根/空窗口、全零目标、跳空穿越保护、同 bar 双触发、反手当天触发保护、
负权益爆仓、极端价格、零成本、防抖带、末根开仓即强平、随机序列不变量。
"""
from __future__ import annotations

import math
import random
import unittest

from _util import bars_from_closes

from agentkline_engine.contract import RunRequest
from agentkline_engine.drivers.signal import run_signal
from agentkline_engine.loader import load_strategy
from agentkline_engine.matching import MatchingEngine


class _Eng:
    id = "builtin"
    version = "0"
    api = 1
    caps = {}
    assumptions = {}


def _src(targets, warmup=0, protection=None):
    prot = f"PROTECTION = {protection!r}\n" if protection else ""
    return (
        'STRATEGY_MODE = "signal"\n'
        'NAME = "edge"\n'
        f"WARMUP = {warmup}\n"
        "PARAMS = {}\n"
        f"{prot}"
        f"TARGETS = {list(targets)!r}\n"
        "def main(params, ohlcv):\n"
        '    return {"target": TARGETS[:len(ohlcv)]}\n'
    )


def _run(bars, targets, warmup=0, direction="both", fee=5.0, slip=5.0,
         protection=None, cash=10_000.0, tolerance=0.0001):
    src = _src(targets, warmup, protection)
    req = RunRequest(bars=bars, strategy_source=src, initial_cash=cash,
                     fee_bps=fee, slippage_bps=slip, direction=direction,
                     protection=protection, rebalance_tolerance=tolerance)
    return run_signal(req, load_strategy(src), _Eng())


def _bar(i, o, h=None, l=None, c=None):
    c = o if c is None else c
    return {"timestamp": 1_600_000_000_000 + i * 86_400_000, "index": i,
            "open": o, "high": o if h is None else h, "low": o if l is None else l,
            "close": c, "volume": 1.0}


class WindowEdgeTest(unittest.TestCase):
    def test_single_bar_no_trade(self):
        res = _run(bars_from_closes([100]), [1.0])
        self.assertEqual(res.status, "no_signals")
        self.assertEqual(res.fills, [])
        self.assertEqual(res.equity["values"], [10_000.0])

    def test_single_eval_bar(self):
        bars = bars_from_closes([100, 101, 102, 103, 104])
        res = _run(bars, [1.0] * 5, warmup=3)
        self.assertEqual(len(res.equity["values"]), 2)  # bar3、bar4
        self.assertEqual(res.status, "completed_trades")

    def test_all_zero_targets(self):
        res = _run(bars_from_closes([100, 105, 110, 90]), [0.0] * 4)
        self.assertEqual(res.status, "no_signals")
        self.assertEqual(res.equity["values"], [10_000.0] * 4)

    def test_warmup_blocks_entry(self):
        bars = bars_from_closes([100, 100, 100, 100])
        res = _run(bars, [1.0, 1.0, 1.0, 1.0], warmup=2)
        # 第 3 根开盘进、同根收盘强平，两笔 fill 同一时间戳
        self.assertEqual([f["time"] for f in res.fills], [bars[3]["timestamp"]] * 2)
        self.assertEqual(res.trades[0]["holding_bars"], 0)

    def test_entry_and_force_close_same_bar(self):
        bars = bars_from_closes([100, 100])
        res = _run(bars, [1.0, 1.0], fee=0.0, slip=0.0)
        self.assertEqual(len(res.trades), 1)
        t = res.trades[0]
        self.assertEqual(t["exit_reason"], "end_of_backtest")
        self.assertEqual(t["holding_bars"], 0)
        self.assertAlmostEqual(t["entry_price"], 100.0)
        self.assertAlmostEqual(t["exit_price"], 100.0)

    def test_flat_bars_no_division_issue(self):
        bars = [{"timestamp": 1_600_000_000_000 + i * 1000, "open": 100.0,
                 "high": 100.0, "low": 100.0, "close": 100.0, "volume": 0.0}
                for i in range(6)]
        res = _run(bars, [0.0, 1.0, 1.0, -1.0, -1.0, 0.0])
        self.assertTrue(all(math.isfinite(v) for v in res.equity["values"]))
        self.assertGreater(len(res.trades), 0)


class ProtectionEdgeTest(unittest.TestCase):
    def _long(self):
        eng = MatchingEngine(1000, fee_bps=0, slippage_bps=0)
        eng.execute_target(_bar(0, 100.0), 1.0, 1000.0)
        self.assertAlmostEqual(eng.pos, 10.0)
        return eng

    def test_stop_triggered_on_entry_bar(self):
        eng = MatchingEngine(1000, fee_bps=0, slippage_bps=0)
        bar = _bar(0, 100.0, h=101.0, l=90.0, c=92.0)
        eng.execute_target(bar, 1.0, 1000.0)
        fills = eng.check_protection(bar, {"stop_loss_pct": 0.05})
        self.assertEqual(len(fills), 1)
        self.assertAlmostEqual(fills[0]["price"], 95.0)
        self.assertEqual(fills[0]["reason"], "stop_loss")
        self.assertEqual(eng.pos, 0.0)

    def test_take_profit_gap_uses_open(self):
        eng = self._long()
        fills = eng.check_protection(_bar(1, 120.0, h=121.0), {"take_profit_pct": 0.10})
        self.assertAlmostEqual(fills[0]["price"], 120.0)
        self.assertEqual(fills[0]["reason"], "take_profit")

    def test_stop_wins_when_both_hit(self):
        eng = self._long()
        fills = eng.check_protection(_bar(1, 100.0, h=120.0, l=90.0),
                                     {"stop_loss_pct": 0.05, "take_profit_pct": 0.10})
        self.assertAlmostEqual(fills[0]["price"], 95.0)
        self.assertEqual(fills[0]["reason"], "stop_loss")

    def test_short_gap_stop_and_take(self):
        eng = MatchingEngine(1000, fee_bps=0, slippage_bps=0)
        eng.execute_target(_bar(0, 100.0), -1.0, 1000.0)
        f = eng.check_protection(_bar(1, 130.0), {"stop_loss_pct": 0.05})
        self.assertAlmostEqual(f[0]["price"], 130.0)
        self.assertEqual(f[0]["reason"], "stop_loss")

        eng = MatchingEngine(1000, fee_bps=0, slippage_bps=0)
        eng.execute_target(_bar(0, 100.0), -1.0, 1000.0)
        f = eng.check_protection(_bar(1, 80.0), {"take_profit_pct": 0.10})
        self.assertAlmostEqual(f[0]["price"], 80.0)
        self.assertEqual(f[0]["reason"], "take_profit")

    def test_flip_then_protection_same_bar(self):
        eng = MatchingEngine(1000, fee_bps=0, slippage_bps=0)
        eng.execute_target(_bar(0, 100.0), 1.0, 1000.0)          # long
        bar = _bar(1, 100.0, h=130.0, l=99.0)
        eng.execute_target(bar, -1.0, eng.equity(100.0))          # 反手做空
        self.assertLess(eng.pos, 0)
        fills = eng.check_protection(bar, {"stop_loss_pct": 0.05})
        self.assertEqual(len(fills), 1)
        self.assertAlmostEqual(fills[0]["price"], 105.0)
        self.assertEqual(eng.pos, 0.0)

    def test_protection_on_last_bar_then_force_close_noop(self):
        eng = self._long()
        eng.check_protection(_bar(1, 100.0, l=90.0), {"stop_loss_pct": 0.05})
        self.assertEqual(eng.force_close(_bar(1, 100.0)), [])
        self.assertEqual(len(eng.trades), 1)


class AccountingEdgeTest(unittest.TestCase):
    def test_zero_cost_buy_and_hold(self):
        bars = bars_from_closes([100, 100, 110, 121])
        res = _run(bars, [1.0] * 4, fee=0.0, slip=0.0)
        self.assertAlmostEqual(res.equity["values"][-1], 12100.0)
        self.assertAlmostEqual(res.trades[0]["pnl"], 2100.0)
        self.assertAlmostEqual(res.stats["total_fees"], 0.0)

    def test_short_blowup_negative_equity(self):
        bars = bars_from_closes([100, 100, 1000, 1000], opens=[100, 100, 1000, 1000])
        res = _run(bars, [-1.0] * 4, fee=0.0, slip=0.0)
        vals = res.equity["values"]
        self.assertTrue(all(math.isfinite(v) for v in vals))
        self.assertLess(vals[-1], 0)
        self.assertAlmostEqual(vals[-1], res.stats["final_value"])
        self.assertAlmostEqual(vals[-1], res.fills[-1]["price"] * 0 + res.stats["final_value"])

    def test_extreme_prices(self):
        for price in (1e-8, 1e9):
            bars = bars_from_closes([price, price, price * 1.1, price * 0.9],
                                    opens=[price, price, price * 1.1, price * 0.9])
            res = _run(bars, [1.0, 1.0, 1.0, 0.0], cash=1e6)
            self.assertTrue(all(math.isfinite(v) for v in res.equity["values"]))
            self.assertGreater(res.equity["values"][-1], 0)

    def test_tolerance_band_blocks_tiny_resize(self):
        bars = bars_from_closes([100, 100, 100, 100])
        res = _run(bars, [1.0, 1.0, 0.9999, 1.0], fee=0.0, slip=0.0, tolerance=0.01)
        self.assertEqual(len(res.fills), 2)  # 只有开仓和强平

    def test_close_then_reopen(self):
        bars = bars_from_closes([100, 100, 100, 100, 100])
        res = _run(bars, [0.0, 1.0, 0.0, 1.0, 0.0], fee=0.0, slip=0.0)
        self.assertEqual(len(res.trades), 2)
        self.assertEqual(res.equity["values"][0], 10_000.0)


class InvariantTest(unittest.TestCase):
    """随机刁钻行情 + 随机目标：账务恒等式必须成立。"""

    def _check(self, res, initial_cash):
        vals = res.equity["values"]
        self.assertTrue(all(math.isfinite(v) for v in vals))
        self.assertEqual(len(vals), len(res.equity["times"]))
        # 末点 = 初始 + 所有回合净盈亏（末根强平，不留浮盈）
        self.assertAlmostEqual(vals[-1] - initial_cash,
                               sum(t["pnl"] for t in res.trades), places=6)
        self.assertAlmostEqual(res.stats["total_fees"],
                               sum(f["fee"] for f in res.fills), places=9)
        self.assertAlmostEqual(sum(t["fee"] for t in res.trades),
                               sum(f["fee"] for f in res.fills), places=9)
        for t in res.trades:
            self.assertAlmostEqual(t["pnl"], t["gross_pnl"] - t["fee"], places=9)
            self.assertGreater(t["size"], 0)
            self.assertGreater(t["entry_price"], 0)
            self.assertGreater(t["exit_price"], 0)
            self.assertGreaterEqual(t["holding_bars"], 0)
            for key in ("entry_time", "exit_time"):
                self.assertIsInstance(t[key], int)
        for f in res.fills:
            self.assertNotEqual(f["signed_qty"], 0)
            self.assertGreater(f["price"], 0)
            self.assertGreaterEqual(f["fee"], 0)

    def test_random_series(self):
        rnd = random.Random(20261021)
        for seed in range(40):
            n = rnd.choice([5, 12, 60, 200])
            price = rnd.choice([0.5, 100.0, 60_000.0])
            bars = []
            prev = price
            for i in range(n):
                gap = rnd.choice([1.0, 1.0, 1.0, 1.05, 0.95, 1.2, 0.8])
                o = prev * gap
                c = o * (1 + rnd.gauss(0, 0.03))
                hi = max(o, c) * (1 + abs(rnd.gauss(0, 0.01)))
                lo = min(o, c) * (1 - abs(rnd.gauss(0, 0.01)))
                bars.append({"timestamp": 1_600_000_000_000 + i * 86_400_000,
                             "open": o, "high": hi, "low": lo, "close": c,
                             "volume": 1.0})
                prev = c
            targets = []
            cur = 0.0
            for _ in range(n):
                if rnd.random() < 0.15:
                    cur = rnd.choice([0.0, 1.0, -1.0, 0.5, -0.5, 0.25])
                targets.append(cur)
            prot = rnd.choice([None, {"stop_loss_pct": 0.02},
                               {"take_profit_pct": 0.05},
                               {"stop_loss_pct": 0.01, "take_profit_pct": 0.02}])
            res = _run(bars, targets, direction=rnd.choice(["both", "long_only"]),
                       fee=rnd.choice([0.0, 5.0, 20.0]), slip=rnd.choice([0.0, 5.0, 15.0]),
                       protection=prot, cash=10_000.0,
                       tolerance=rnd.choice([0.0, 0.0001, 0.002]))
            with self.subTest(seed=seed):
                self._check(res, 10_000.0)


if __name__ == "__main__":
    unittest.main()
