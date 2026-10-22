#!/usr/bin/env python3
"""引擎子进程边界与策略保存校验（M3 B1/B2/B4/B5/B10）。

    python tools/test_backtest_unit.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentkline.backtest import runner  # noqa: E402
from agentkline.core.script_engine import ScriptEngine  # noqa: E402

BARS = [{"timestamp": 1_600_000_000_000 + i * 86_400_000,
         "open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i,
         "close": 100.5 + i, "volume": 1.0} for i in range(40)]
GOOD = (
    'STRATEGY_MODE = "signal"\nNAME = "t"\nWARMUP = 2\nPARAMS = {}\n'
    'def main(params, ohlcv):\n'
    '    return {"target": [0.0, 0.0] + [1.0] * (len(ohlcv) - 2)}\n'
)


def spec(source=GOOD, bars=None, engine="builtin", run=None):
    return {"api": 1, "engine": engine, "bars": bars or BARS,
            "strategy": {"source": source},
            "run": run or {"initial_cash": 10000, "fee_bps": 5, "slippage_bps": 5},
            "timeframe": "1d"}


class FakeCmd:
    """把 engine_cmd 临时替换成一段 python -c。"""

    def __init__(self, code: str):
        self.code = code
        self._orig = None

    def __enter__(self):
        self._orig = runner.engine_cmd
        runner.engine_cmd = lambda: [sys.executable, "-c", self.code]
        return self

    def __exit__(self, *exc):
        runner.engine_cmd = self._orig


class RunnerTest(unittest.TestCase):
    def test_list_engines(self):
        engines = runner.list_engines()
        ids = [e["id"] for e in engines]
        self.assertIn("builtin", ids)
        builtin = next(e for e in engines if e["id"] == "builtin")
        self.assertEqual(builtin["api"], 1)
        self.assertTrue(builtin["caps"]["signal"])

    def test_run_spec(self):
        res = runner.run_spec(spec(), timeout=60)
        self.assertEqual(res["schema"], 1)
        self.assertEqual(res["status"], "completed_trades")
        self.assertEqual(len(res["equity"]["times"]), len(res["equity"]["values"]))
        self.assertGreaterEqual(res["_elapsed_ms"], 0)
        self.assertEqual(res["engine"]["id"], "builtin")

    def test_engine_error_code(self):
        with self.assertRaises(runner.EngineRunError) as cm:
            runner.run_spec(spec(source="NAME='x'"), timeout=60)
        self.assertEqual(cm.exception.code, "MAIN_MISSING")
        self.assertEqual(cm.exception.exit_code, 2)

    def test_stray_stdout_is_tolerated(self):
        code = (
            "import sys\n"
            "sys.stdout.write('noise before\\n')\n"
            f"sys.stdout.write({runner.SENTINEL!r} + '\\n')\n"
            "sys.stdout.write('{\"ok\": true}\\n')\n"
        )
        with FakeCmd(code):
            res = runner.invoke(["run", "--stdin"], "{}", timeout=10)
        self.assertTrue(res["ok"])

    def test_crash_os_exit(self):
        with FakeCmd("import os; os._exit(7)"):
            with self.assertRaises(runner.EngineRunError) as cm:
                runner.invoke(["run", "--stdin"], "{}", timeout=10)
        self.assertEqual(cm.exception.code, "ENGINE_CRASH")
        self.assertEqual(cm.exception.exit_code, 7)

    def test_crash_segfault(self):
        with FakeCmd("import ctypes; ctypes.string_at(0)"):
            with self.assertRaises(runner.EngineRunError) as cm:
                runner.invoke(["run", "--stdin"], "{}", timeout=10)
        self.assertEqual(cm.exception.code, "ENGINE_CRASH")
        self.assertLess(cm.exception.exit_code, 0)

    def test_timeout_kills_group(self):
        t0 = time.perf_counter()
        with FakeCmd("import time; time.sleep(30)"):
            with self.assertRaises(runner.EngineRunError) as cm:
                runner.invoke(["run", "--stdin"], "{}", timeout=0.6)
        elapsed = time.perf_counter() - t0
        self.assertEqual(cm.exception.code, "RUN_TIMEOUT")
        self.assertLess(elapsed, 5.0, f"超时没有及时终止：{elapsed:.1f}s")

    def test_error_payload_without_code(self):
        code = ("import sys\n"
                f"sys.stdout.write({runner.SENTINEL!r} + '\\n')\n"
                "sys.stdout.write('{\"error\": {\"message\": \"boom\"}}\\n')\n")
        with FakeCmd(code):
            with self.assertRaises(runner.EngineRunError) as cm:
                runner.invoke(["run", "--stdin"], "{}", timeout=10)
        self.assertEqual(cm.exception.code, "ENGINE_INTERNAL")


class SaveStrategyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.se = ScriptEngine(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_strategy_saves(self):
        r = self.se.save_script("strategy/ok", GOOD)
        self.assertTrue(r.get("ok"), r)
        self.assertTrue((Path(self.tmp.name) / "strategy" / "ok.py").exists())

    def test_mode_mismatch(self):
        r = self.se.save_script("strategy/bad", GOOD.replace('"signal"', '"event"'))
        self.assertIn("MODE_MISMATCH", r.get("error", ""))
        self.assertFalse((Path(self.tmp.name) / "strategy" / "bad.py").exists())

    def test_protection_unknown_key(self):
        src = GOOD.replace('PARAMS = {}', 'PARAMS = {}\nPROTECTION = {"trailing": 0.1}')
        r = self.se.save_script("strategy/bad2", src)
        self.assertIn("PROTECTION_UNKNOWN_KEY", r.get("error", ""))

    def test_indicator_script_unaffected(self):
        code = 'NAME = "x"\nPARAMS = {}\ndef main(params, ohlcv):\n    return {"values": []}\n'
        r = self.se.save_script("indicator/plain", code)
        self.assertTrue(r.get("ok"), r)

    def test_strategy_requires_main(self):
        r = self.se.save_script("strategy/nomain", 'STRATEGY_MODE = "signal"\n')
        self.assertIn("SAVE_NO_MAIN", r.get("error", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
