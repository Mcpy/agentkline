"""依赖隔离：core 不拉后端，builtin 不拉 fastapi/uvicorn（G1 E1/E15）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from _util import ROOT

CORE_CODE = r"""
import json, sys
import agentkline_engine.cli
bad = sorted(m for m in sys.modules
             if m == "agentkline" or m.startswith(("agentkline.", "fastapi", "uvicorn",
                                                   "starlette", "vela")))
print(json.dumps({"bad": bad, "count": len(sys.modules)}))
"""

BUILTIN_CODE = r"""
import json, sys
from agentkline.engines.builtin import BuiltinEngine
bad = sorted(m for m in sys.modules
             if m.startswith(("fastapi", "uvicorn", "starlette", "vela"))
             or m in ("agentkline.api", "agentkline.core", "agentkline.mcp_server",
                      "agentkline.state"))
print(json.dumps({"bad": bad, "id": BuiltinEngine.id, "api": BuiltinEngine.api}))
"""


def _run(code):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=str(ROOT), env=env, timeout=120)
    if p.returncode != 0:
        raise AssertionError(p.stderr)
    return json.loads(p.stdout.strip().splitlines()[-1])


class ImportIsolationTest(unittest.TestCase):
    def test_core_does_not_import_backend(self):
        out = _run(CORE_CODE)
        self.assertEqual(out["bad"], [], f"core import 图污染: {out['bad']}")

    def test_builtin_does_not_import_backend(self):
        out = _run(BUILTIN_CODE)
        self.assertEqual(out["bad"], [], f"builtin import 图污染: {out['bad']}")
        self.assertEqual(out["id"], "builtin")
        self.assertEqual(out["api"], 1)


if __name__ == "__main__":
    unittest.main()
