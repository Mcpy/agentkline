"""策略加载与参数校验（G1 E3）。"""
from __future__ import annotations

import unittest

from _util import CASES

from agentkline_engine.errors import AKError
from agentkline_engine.loader import check_source, describe_source, load_strategy, load_strategy_file

BASE = """
STRATEGY_MODE = "signal"
NAME = "t"
WARMUP = 5
PARAMS = {"n": 3}
def main(params, ohlcv):
    return {"target": [0.0] * len(ohlcv)}
"""


class LoaderTest(unittest.TestCase):
    def test_valid_file(self):
        st = load_strategy_file(str(CASES / "strategy_ma.py"))
        self.assertEqual(st.mode, "signal")
        self.assertEqual(st.warmup, 20)
        self.assertEqual(st.params["fast"], 5)
        self.assertEqual(len(st.source_sha256), 64)

    def test_missing_main(self):
        src = BASE.replace("def main(params, ohlcv):", "def not_main(params, ohlcv):")
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "MAIN_MISSING")

    def test_mode_mismatch(self):
        src = BASE.replace('STRATEGY_MODE = "signal"', 'STRATEGY_MODE = "event"')
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "MODE_MISMATCH")

    def test_protection_unknown_key(self):
        src = BASE.replace('PARAMS = {"n": 3}', 'PARAMS = {"n": 3}\nPROTECTION = {"trailing_pct": 0.05}')
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "PROTECTION_UNKNOWN_KEY")

    def test_protection_range(self):
        src = BASE.replace('PARAMS = {"n": 3}', 'PARAMS = {"n": 3}\nPROTECTION = {"stop_loss_pct": 1.5}')
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "PROTECTION_INVALID")

    def test_params_not_dict(self):
        src = BASE.replace('PARAMS = {"n": 3}', 'PARAMS = [3]')
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "PARAMS_INVALID")

    def test_params_nested_value(self):
        src = BASE.replace('PARAMS = {"n": 3}', 'PARAMS = {"n": {"x": 1}}')
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "PARAMS_INVALID")

    def test_missing_warmup(self):
        src = BASE.replace("WARMUP = 5", "")
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "STRATEGY_INVALID")

    def test_nonliteral_decl(self):
        src = BASE.replace("WARMUP = 5", "WARMUP = 2 + 3")
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "STRATEGY_INVALID")

    def test_param_meta_unknown_key(self):
        src = BASE.replace('PARAMS = {"n": 3}',
                           'PARAMS = {"n": 3}\nPARAM_META = {"n": {"typo": 1}}')
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "PARAMS_INVALID")

    def test_param_meta_for_undeclared(self):
        src = BASE.replace('PARAMS = {"n": 3}',
                           'PARAMS = {"n": 3}\nPARAM_META = {"m": {"type": "int"}}')
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "PARAMS_INVALID")

    def test_resolve_params(self):
        st = load_strategy(BASE)
        self.assertEqual(st.resolved({"n": 7}), {"n": 7})
        with self.assertRaises(AKError) as cm:
            st.resolved({"nope": 1})
        self.assertEqual(cm.exception.code, "PARAM_UNKNOWN")

    def test_resolve_params_type_and_range(self):
        st = load_strategy_file(str(CASES / "strategy_ma.py"))
        self.assertEqual(st.resolved({"fast": "8"}), {"fast": 8, "slow": 15})
        with self.assertRaises(AKError) as cm:
            st.resolved({"fast": 1})
        self.assertEqual(cm.exception.code, "PARAMS_INVALID")
        with self.assertRaises(AKError) as cm:
            st.resolved({"fast": 500})
        self.assertEqual(cm.exception.code, "PARAMS_INVALID")
        with self.assertRaises(AKError) as cm:
            st.resolved({"fast": 3.5})
        self.assertEqual(cm.exception.code, "PARAMS_INVALID")

    def test_check_source_does_not_execute(self):
        src = BASE.replace('NAME = "t"', 'NAME = "t"\nraise RuntimeError("boom")')
        self.assertEqual(check_source(src), [])
        info = describe_source(src)
        self.assertEqual(info["name"], "t")
        self.assertEqual(info["warmup"], 5)
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "STRATEGY_INVALID")

    def test_syntax_error(self):
        errors = check_source("def main(:\n")
        self.assertEqual(errors[0]["code"], "STRATEGY_INVALID")

    def test_main_signature(self):
        src = BASE.replace("def main(params, ohlcv):", "def main(params):")
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "STRATEGY_INVALID")


if __name__ == "__main__":
    unittest.main()
