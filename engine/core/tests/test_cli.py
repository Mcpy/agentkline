"""CLI 协议：哨兵、stdin/stdout、错误码、print 重定向（G1 E1/E2/E3）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _util import CASES, ROOT

EXE = Path(sys.executable).with_name("ak-engine")


def _cmd():
    if EXE.exists():
        return [str(EXE)]
    return [sys.executable, "-m", "agentkline_engine.cli"]


def run_cli(args, *, stdin=None, cwd=ROOT):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(_cmd() + args, input=stdin, capture_output=True, text=True,
                          cwd=str(cwd), env=env, timeout=120)


def parse(proc):
    lines = proc.stdout.splitlines()
    assert lines and lines[0] == "__AK_RESULT__", f"缺少哨兵: {proc.stdout[:200]!r}"
    return json.loads(lines[1])


class CliTest(unittest.TestCase):
    def test_list(self):
        p = run_cli(["list", "--json"])
        self.assertEqual(p.returncode, 0, p.stderr)
        payload = parse(p)
        ids = [e["id"] for e in payload["engines"]]
        self.assertIn("builtin", ids)
        builtin = next(e for e in payload["engines"] if e["id"] == "builtin")
        self.assertEqual(builtin["api"], 1)
        self.assertTrue(builtin["caps"]["signal"])

    def test_run_spec_and_out(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "r.json"
            p = run_cli(["run", "--spec", str(CASES / "ma_long.json"), "--out", str(out)])
            self.assertEqual(p.returncode, 0, p.stderr)
            payload = parse(p)
            self.assertEqual(payload["schema"], 1)
            self.assertEqual(payload["status"], "completed_trades")
            for key in ("fills", "trades", "equity", "stats", "assumptions"):
                self.assertIn(key, payload)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), payload)

    def test_run_stdin_inline(self):
        spec = {
            "api": 1,
            "engine": "builtin",
            "bars": [{"timestamp": 1600000000000 + i * 86400000,
                      "open": 100 + i, "high": 101 + i, "low": 99 + i,
                      "close": 100.5 + i, "volume": 1} for i in range(30)],
            "strategy": {"source":
                         'STRATEGY_MODE="signal"\nNAME="up"\nWARMUP=1\nPARAMS={}\n'
                         'def main(params, ohlcv):\n'
                         '    return {"target": [0.0] + [1.0] * (len(ohlcv) - 1)}\n'},
            "run": {"initial_cash": 1000, "fee_bps": 0, "slippage_bps": 0},
        }
        p = run_cli(["run", "--stdin"], stdin=json.dumps(spec))
        self.assertEqual(p.returncode, 0, p.stderr)
        payload = parse(p)
        self.assertEqual(payload["status"], "completed_trades")
        self.assertEqual(len(payload["trades"]), 1)

    def test_strategy_print_goes_to_stderr(self):
        spec = {
            "api": 1,
            "engine": "builtin",
            "bars": [{"timestamp": 1600000000000 + i * 86400000,
                      "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}
                     for i in range(5)],
            "strategy": {"source":
                         'STRATEGY_MODE="signal"\nNAME="noisy"\nWARMUP=0\nPARAMS={}\n'
                         'print("module-level-print")\n'
                         'def main(params, ohlcv):\n'
                         '    print("inside-main")\n'
                         '    return {"target": [0.0] * len(ohlcv)}\n'},
            "run": {},
        }
        p = run_cli(["run", "--stdin"], stdin=json.dumps(spec))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.count("__AK_RESULT__"), 1)
        self.assertNotIn("module-level-print", p.stdout)
        self.assertNotIn("inside-main", p.stdout)
        self.assertIn("module-level-print", p.stderr)
        self.assertIn("inside-main", p.stderr)
        parse(p)

    def test_unknown_engine(self):
        spec = {"api": 1, "engine": "nope",
                "bars": [{"timestamp": 1, "open": 1, "high": 1, "low": 1, "close": 1}],
                "strategy": {"source": 'STRATEGY_MODE="signal"\nNAME="x"\nWARMUP=0\nPARAMS={}\n'
                                       'def main(p, o):\n    return {"target": [0.0]}\n'},
                "run": {}}
        p = run_cli(["run", "--stdin"], stdin=json.dumps(spec))
        self.assertEqual(p.returncode, 2)
        self.assertEqual(parse(p)["error"]["code"], "ENGINE_NOT_FOUND")

    def test_bad_strategy_error_code(self):
        spec = {"api": 1, "engine": "builtin",
                "bars": [{"timestamp": 1, "open": 1, "high": 1, "low": 1, "close": 1}],
                "strategy": {"source": 'STRATEGY_MODE="signal"\nNAME="x"\nWARMUP=0\nPARAMS={}\n'},
                "run": {}}
        p = run_cli(["run", "--stdin"], stdin=json.dumps(spec))
        self.assertEqual(p.returncode, 2)
        self.assertEqual(parse(p)["error"]["code"], "MAIN_MISSING")

    def test_bad_api(self):
        spec = {"api": 9, "engine": "builtin", "bars": [], "strategy": {}, "run": {}}
        p = run_cli(["run", "--stdin"], stdin=json.dumps(spec))
        self.assertEqual(p.returncode, 2)
        self.assertEqual(parse(p)["error"]["code"], "API_MISMATCH")

    def test_validate_strategy(self):
        p = run_cli(["validate-strategy", str(CASES / "strategy_ma.py"), "--json"])
        self.assertEqual(p.returncode, 0, p.stderr)
        payload = parse(p)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["params"], {"fast": 5, "slow": 15})

        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.py"
            bad.write_text('STRATEGY_MODE="event"\nNAME="x"\nWARMUP=0\nPARAMS={}\n'
                           'def main(p, o):\n    return {}\n', encoding="utf-8")
            p = run_cli(["validate-strategy", str(bad), "--json"])
            self.assertEqual(p.returncode, 2)
            payload = parse(p)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["errors"][0]["code"], "MODE_MISMATCH")


if __name__ == "__main__":
    unittest.main()
