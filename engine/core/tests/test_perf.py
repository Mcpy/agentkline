"""性能基线（G1 E13）：5 万根 1d、单策略 < 3s；内存峰值 < 500MB。"""
from __future__ import annotations

import math
import resource
import time
import unittest

import _util  # noqa: F401  - 路径

from agentkline_engine.contract import RunRequest
from agentkline_engine.drivers.signal import run_signal
from agentkline_engine.loader import load_strategy

N = 50_000

STRAT = """
STRATEGY_MODE = "signal"
NAME = "perf_ma"
WARMUP = 60
PARAMS = {"fast": 20, "slow": 60}
def main(params, ohlcv):
    fast, slow = params["fast"], params["slow"]
    closes = [b["close"] for b in ohlcv]
    pre = [0.0]
    for c in closes:
        pre.append(pre[-1] + c)
    n = len(closes)
    out = [0.0] * n
    for i in range(slow - 1, n):
        f = (pre[i + 1] - pre[i + 1 - fast]) / fast
        s = (pre[i + 1] - pre[i + 1 - slow]) / slow
        out[i] = 1.0 if f > s else -1.0
    return {"target": out}
"""


def make_bars(n=N):
    """正弦趋势 + 高频噪声：保证均线反复穿越，不是单边行情。"""
    bars = []
    ts = 1_500_000_000_000
    prev = 10_000.0
    for i in range(n):
        c = 10_000.0 * (1.0 + 0.08 * math.sin(i / 40.0) + 0.01 * math.sin(i / 3.0))
        o = prev
        bars.append({"timestamp": ts + i * 86_400_000, "open": o,
                     "high": max(o, c) * 1.001, "low": min(o, c) * 0.999,
                     "close": c, "volume": 1.0})
        prev = c
    return bars


class PerfTest(unittest.TestCase):
    def test_50k_bars(self):
        bars = make_bars()
        strategy = load_strategy(STRAT)

        class Eng:
            id = "builtin"
            version = "0"
            api = 1
            caps = {}
            assumptions = {}

        req = RunRequest(bars=bars, strategy_source=STRAT, initial_cash=100_000.0,
                         direction="long_only", timeframe="1d")
        t0 = time.perf_counter()
        res = run_signal(req, strategy, Eng())
        elapsed = time.perf_counter() - t0
        self.assertEqual(res.bars["count"], N)
        self.assertGreater(len(res.trades), 10)
        self.assertLess(elapsed, 3.0, f"5 万根耗时 {elapsed:.2f}s")
        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        self.assertLess(rss_mb, 500.0, f"内存峰值 {rss_mb:.0f}MB")


if __name__ == "__main__":
    unittest.main()
