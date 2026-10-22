"""golden 快照 + 确定性（G1 E12/E14）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from _util import HERE, ROOT, assert_deep_equal, build, expected, spec

from agentkline_engine.registry import get_engine

GOLDEN = ("ma_long", "ma_short", "stock_both_protection")


class GoldenTest(unittest.TestCase):
    def test_snapshots(self):
        for name in GOLDEN:
            with self.subTest(case=name):
                want = expected(name)
                got = get_engine("builtin").run(build(name)).to_dict()
                assert_deep_equal(self, got, want, msg=name)

    def test_repeatable_in_process(self):
        a = get_engine("builtin").run(build("ma_long")).to_dict()
        b = get_engine("builtin").run(build("ma_long")).to_dict()
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))


class DeterminismTest(unittest.TestCase):
    def test_hashseed_and_tz(self):
        code = (
            "import json, sys\n"
            f"sys.path.insert(0, {str(HERE)!r})\n"
            "from _util import build\n"
            "from agentkline_engine.registry import get_engine\n"
            "print(json.dumps(get_engine('builtin').run(build('ma_long')).to_dict(),"
            " sort_keys=True))\n"
        )
        outs = []
        for seed, tz in (("0", "UTC"), ("12345", "Asia/Shanghai")):
            env = dict(os.environ)
            env.update({"PYTHONHASHSEED": seed, "TZ": tz,
                        "PYTHONPATH": str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")})
            p = subprocess.run([sys.executable, "-c", code], capture_output=True,
                               text=True, cwd=str(ROOT), env=env, timeout=180)
            self.assertEqual(p.returncode, 0, p.stderr)
            outs.append(p.stdout.strip())
        self.assertEqual(outs[0], outs[1])


if __name__ == "__main__":
    unittest.main()
