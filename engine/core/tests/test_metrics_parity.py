"""统计口径与主包 0.6.0 逐字段一致（G1 E10）。

core 是独立包，不能 import 主包；测试环境里主包可用，就在这里做对照。
"""
from __future__ import annotations

import copy
import unittest

from _util import CASES

from agentkline_engine.metrics import compute_stats_full as core_stats
from agentkline_engine.bars import read_csv
from agentkline_engine.contract import RunRequest
from agentkline_engine.drivers.signal import run_signal
from agentkline_engine.loader import load_strategy

from agentkline.core import results as main_results


class StatsParityTest(unittest.TestCase):
    def _compare(self, times, values, trades, cash, bpy):
        a = core_stats(times, values, copy.deepcopy(trades), cash, bpy, fills=[])
        b = main_results.compute_stats_full(times, values, copy.deepcopy(trades), cash, bpy,
                                            fills=[])
        self.assertEqual(set(a), set(b))
        for k in a:
            if isinstance(a[k], float):
                self.assertAlmostEqual(a[k], b[k], places=12, msg=k)
            else:
                self.assertEqual(a[k], b[k], msg=k)

    def test_synthetic_series(self):
        times = [1_600_000_000_000 + i * 86_400_000 for i in range(40)]
        values = [1000 * (1 + 0.01 * ((i * 7) % 11 - 5) / 10) for i in range(40)]
        trades = [
            {"pnl": 12.5, "fee": 1.0, "holding_bars": 3,
             "entry_time": times[1], "exit_time": times[5]},
            {"pnl": -4.0, "fee": 0.5, "holding_bars": 2,
             "entry_time": times[8], "exit_time": times[12]},
            {"pnl": 0.0, "fee": 0.2, "holding_bars": 1,
             "entry_time": times[15], "exit_time": times[16]},
        ]
        self._compare(times, values, trades, 1000.0, 365)

    def test_empty_and_single(self):
        self._compare([], [], [], 1000.0, 365)
        self._compare([1_600_000_000_000], [1000.0], [], 1000.0, 365)

    def test_engine_result_matches_main_stats(self):
        req = RunRequest(
            bars=read_csv(str(CASES / "btc_1d_200.csv")),
            strategy_source=(CASES / "strategy_ma.py").read_text(encoding="utf-8"),
            initial_cash=10_000.0,
        )
        res = run_signal(req, load_strategy(req.strategy_source), _Eng())
        b = main_results.compute_stats_full(
            res.equity["times"], res.equity["values"], copy.deepcopy(res.trades),
            req.initial_cash, int(round(res.assumptions["bars_per_year"])),
            fills=copy.deepcopy(res.fills))
        for k, v in res.stats.items():
            if isinstance(v, float):
                self.assertAlmostEqual(v, b[k], places=12, msg=k)
            else:
                self.assertEqual(v, b[k], msg=k)
        # total_fees 与 fills 费用之和一致（builtin 末根强平）
        self.assertAlmostEqual(res.stats["total_fees"],
                               sum(f["fee"] for f in res.fills), places=9)


class _Eng:
    id = "test"
    version = "0"
    api = 1
    caps = {}
    assumptions = {}


if __name__ == "__main__":
    unittest.main()
