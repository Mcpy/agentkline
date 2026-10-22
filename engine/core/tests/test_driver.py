"""signal 驱动：方向过滤、target 校验、状态、权益（G1 E4/E9/E10 的驱动侧）。"""
from __future__ import annotations

import unittest

from _util import bars_from_closes

from agentkline_engine.contract import RunRequest
from agentkline_engine.drivers.signal import apply_direction, normalize_targets, run_signal
from agentkline_engine.errors import AKError
from agentkline_engine.loader import load_strategy

STRAT = """
STRATEGY_MODE = "signal"
NAME = "fixed"
WARMUP = 1
PARAMS = {}
def main(params, ohlcv):
    return {"target": [0.0, 1.0, -1.0, -1.0, 1.0, 0.0], "reason": ["r"] * 6}
"""


def _req(direction="long_only", **kw):
    bars = bars_from_closes([100, 100, 101, 102, 103, 104])
    base = dict(bars=bars, strategy_source=STRAT, initial_cash=1000.0,
                fee_bps=0.0, slippage_bps=0.0, direction=direction)
    base.update(kw)
    return RunRequest(**base)


class DirectionTest(unittest.TestCase):
    def _sides(self, direction):
        res = run_signal(_req(direction), load_strategy(STRAT), _Engine())
        return [t["side"] for t in res.trades], res.warnings

    def test_long_only_clamps_shorts(self):
        sides, warns = self._sides("long_only")
        self.assertTrue(sides)
        self.assertTrue(all(s == "long" for s in sides))
        self.assertTrue(any(w.startswith("direction_clamped=") for w in warns))

    def test_short_only_clamps_longs(self):
        sides, warns = self._sides("short_only")
        self.assertTrue(sides)
        self.assertTrue(all(s == "short" for s in sides))
        self.assertTrue(any(w.startswith("direction_clamped=") for w in warns))

    def test_both_keeps_both(self):
        sides, warns = self._sides("both")
        self.assertIn("long", sides)
        self.assertIn("short", sides)
        self.assertFalse(any(w.startswith("direction_clamped=") for w in warns))

    def test_all_clamped_is_no_signals(self):
        src = STRAT.replace("[0.0, 1.0, -1.0, -1.0, 1.0, 0.0]", "[0.0, -1.0, -1.0, -1.0, -1.0, 0.0]")
        req = _req("long_only", strategy_source=src)
        res = run_signal(req, load_strategy(src), _Engine())
        self.assertEqual(res.status, "no_signals")
        self.assertEqual(res.fills, [])
        self.assertIn("direction_clamped=4", res.warnings)


class TargetTest(unittest.TestCase):
    def _run(self, out):
        src = STRAT.replace('{"target": [0.0, 1.0, -1.0, -1.0, 1.0, 0.0], "reason": ["r"] * 6}',
                            out)
        req = _req(strategy_source=src)
        return run_signal(req, load_strategy(src), _Engine())

    def test_length_mismatch(self):
        with self.assertRaises(AKError) as cm:
            self._run('{"target": [0.0, 1.0]}')
        self.assertEqual(cm.exception.code, "TARGET_LENGTH")

    def test_nonfinite(self):
        with self.assertRaises(AKError) as cm:
            self._run('{"target": [0.0, float("nan"), 0.0, 0.0, 0.0, 0.0]}')
        self.assertEqual(cm.exception.code, "TARGET_NONFINITE")

    def test_not_numeric(self):
        with self.assertRaises(AKError) as cm:
            self._run('{"target": [0.0, "x", 0.0, 0.0, 0.0, 0.0]}')
        self.assertEqual(cm.exception.code, "TARGET_INVALID")

    def test_clipping(self):
        res = self._run('{"target": [0.0, 3.0, -2.0, 0.0, 0.0, 0.0]}')
        self.assertIn("target_clipped=2", res.warnings)
        # 裁到 1.0 后名义上限就是权益（+滑点容差），不会出现 3 倍杠杆
        self.assertLessEqual(max(t["notional"] for t in res.trades), 1000.0)

    def test_bare_list_allowed(self):
        res = self._run("[0.0, 1.0, 0.0, 0.0, 0.0, 0.0]")
        self.assertEqual(len(res.trades), 1)


class WindowTest(unittest.TestCase):
    def test_warmup_blocks_first_bars(self):
        res = run_signal(_req("both"), load_strategy(STRAT), _Engine())
        self.assertEqual(res.equity["times"][0], _req().bars[1]["timestamp"])
        self.assertEqual(len(res.equity["values"]), 5)

    def test_eval_end_truncates(self):
        src = STRAT.replace(
            '{"target": [0.0, 1.0, -1.0, -1.0, 1.0, 0.0], "reason": ["r"] * 6}',
            '{"target": [0.0, 1.0, -1.0, -1.0, 1.0, 0.0][:len(ohlcv)],'
            ' "reason": ["r"] * len(ohlcv)}')
        req = _req("both", eval_end=3, strategy_source=src)
        res = run_signal(req, load_strategy(src), _Engine())
        self.assertEqual(res.bars["count"], 4)
        self.assertEqual(len(res.equity["values"]), 3)

    def test_eval_start_can_be_after_warmup(self):
        req = _req("both", eval_start=3)
        res = run_signal(req, load_strategy(STRAT), _Engine())
        self.assertEqual(res.equity["times"][0], req.bars[3]["timestamp"])

    def test_empty_window(self):
        req = _req("both", eval_start=6)
        with self.assertRaises(AKError) as cm:
            run_signal(req, load_strategy(STRAT), _Engine())
        self.assertEqual(cm.exception.code, "INPUT_INVALID")

    def test_force_close_last_bar_eq_cash(self):
        req = _req("both")
        res = run_signal(req, load_strategy(STRAT), _Engine())
        self.assertEqual(res.status, "completed_trades")
        self.assertEqual(res.trades[-1]["exit_reason"], "end_of_backtest")
        self.assertAlmostEqual(res.trades[-1]["exit_price"], req.bars[-1]["close"])
        self.assertAlmostEqual(res.stats["final_value"], res.equity["values"][-1])
        self.assertEqual(res.stats["total_fees"], sum(f["fee"] for f in res.fills))


class _Engine:
    id = "test"
    version = "0"
    api = 1
    caps = {}
    assumptions = {}


if __name__ == "__main__":
    unittest.main()
