"""行情输入层与年化口径（G1 E11）。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _util import CASES

from agentkline_engine.bars import bars_meta, load_bars, normalize_bars, read_csv, to_ms
from agentkline_engine.errors import AKError
from agentkline_engine.metrics import observed_bars_per_year


class TimestampTest(unittest.TestCase):
    def test_units_and_iso(self):
        self.assertEqual(to_ms(1_600_000_000), 1_600_000_000_000)
        self.assertEqual(to_ms(1_600_000_000_000), 1_600_000_000_000)
        self.assertEqual(to_ms("2020-09-13"), 1_599_955_200_000)
        self.assertEqual(to_ms("2020-09-13T00:00:00Z"), 1_599_955_200_000)
        self.assertEqual(to_ms("2020-09-13T08:00:00+08:00"), 1_599_955_200_000)
        self.assertIsNone(to_ms("not-a-date"))


class NormalizeTest(unittest.TestCase):
    def test_sort_and_dedupe(self):
        raw = [
            {"timestamp": 3000, "open": 2, "high": 3, "low": 1, "close": 2},
            {"timestamp": 1000, "open": 1, "high": 2, "low": 1, "close": 1},
            {"timestamp": 3000, "open": 5, "high": 6, "low": 4, "close": 5},
        ]
        bars, warns = normalize_bars(raw)
        self.assertEqual([b["timestamp"] for b in bars], [1000, 3000])
        self.assertEqual(bars[-1]["open"], 5)  # 重复保留最后一条
        self.assertIn("bars_deduped=1", warns)
        self.assertEqual(bars[0]["volume"], 0.0)

    def test_array_rows(self):
        bars, _ = normalize_bars([[1000, 1, 2, 0.5, 1.5, 10]])
        self.assertEqual(bars[0]["close"], 1.5)
        self.assertEqual(bars[0]["volume"], 10.0)

    def test_bad_ohlc(self):
        with self.assertRaises(AKError) as cm:
            normalize_bars([{"timestamp": 1, "open": 1, "high": 1, "low": 2, "close": 1}])
        self.assertEqual(cm.exception.code, "BARS_INVALID")
        with self.assertRaises(AKError):
            normalize_bars([{"timestamp": 1, "open": "x", "high": 1, "low": 1, "close": 1}])

    def test_empty(self):
        with self.assertRaises(AKError):
            normalize_bars([])


class ReadTest(unittest.TestCase):
    def test_csv(self):
        bars = read_csv(str(CASES / "btc_1d_200.csv"))
        self.assertEqual(len(bars), 200)
        self.assertTrue(all(b["high"] >= b["low"] for b in bars))
        meta = bars_meta(bars, "1d")
        self.assertEqual(meta["count"], 200)
        self.assertEqual(meta["timeframe"], "1d")

    def test_json_and_inline(self):
        bars = read_csv(str(CASES / "btc_1d_200.csv"))[:3]
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bars.json"
            p.write_text(json.dumps({"bars": bars}), encoding="utf-8")
            self.assertEqual(len(load_bars({"path": str(p), "format": "json"})), 3)
        inline = [dict(b) for b in bars]
        self.assertEqual(len(load_bars(inline)), 3)

    def test_missing_file(self):
        with self.assertRaises(AKError) as cm:
            read_csv("/nonexistent/bars.csv")
        self.assertEqual(cm.exception.code, "BARS_INVALID")


class AnnualizationTest(unittest.TestCase):
    def test_daily_crypto(self):
        bars = read_csv(str(CASES / "btc_1d_200.csv"))
        bpy = observed_bars_per_year([b["timestamp"] for b in bars])
        self.assertGreater(bpy, 350)
        self.assertLess(bpy, 380)

    def test_weekday_only_equity(self):
        # 合成数据只跳周末、不跳节假日：约 261 根/年；真实交易所日历（含节假日）约 252。
        bars = read_csv(str(CASES / "stock_1d_500.csv"))
        bpy = observed_bars_per_year([b["timestamp"] for b in bars])
        self.assertGreater(bpy, 250)
        self.assertLess(bpy, 266)

    def test_short_sample_falls_back_to_median_dt(self):
        bars = read_csv(str(CASES / "weekly_20.csv"))
        bpy = observed_bars_per_year([b["timestamp"] for b in bars])
        self.assertAlmostEqual(bpy, 365 / 7, places=6)

    def test_single_bar(self):
        self.assertEqual(observed_bars_per_year([123]), 365.0)


if __name__ == "__main__":
    unittest.main()
