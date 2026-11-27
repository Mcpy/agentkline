"""event 范式：loader 错误码、warmup、ctx、state、target 与跨范式对账（0.7.5）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from _util import CASES, ROOT, bars_from_closes, assert_deep_equal

from agentkline_engine.cli import build_request
from agentkline_engine.contract import RunRequest
from agentkline_engine.drivers.event import EventContext, normalize_event_return, run_event
from agentkline_engine.errors import AKError
from agentkline_engine.loader import (check_source, describe_source, ensure_state_json,
                                      load_strategy, load_strategy_file)
from agentkline_engine.matching import MatchingEngine
from agentkline_engine.registry import get_engine

EXE = Path(sys.executable).with_name("ak-engine")


class _Engine:
    id = "test"
    version = "0"
    api = 1
    caps = {"event": True}
    assumptions = {}


def _src(body: str, *, warmup: int = 0, params: str = '{"n": 2}',
         init: str = "", main: str = "") -> str:
    return (
        'STRATEGY_MODE = "event"\n'
        'NAME = "ev"\n'
        f"WARMUP = {warmup}\n"
        f"PARAMS = {params}\n"
        f"{init}\n"
        f"{main}\n"
        "def on_bar(state, bar, ctx):\n"
        + "".join(f"    {line}\n" for line in body.splitlines())
    )


def _bars(n: int = 8):
    return bars_from_closes([100 + i for i in range(n)])


def _req(source: str, bars=None, **kw) -> RunRequest:
    base = dict(bars=bars or _bars(), strategy_source=source, initial_cash=1000.0,
                fee_bps=0.0, slippage_bps=0.0, direction="both")
    base.update(kw)
    return RunRequest(**base)


def _run(source: str, bars=None, **kw):
    return run_event(_req(source, bars, **kw), load_strategy(source), _Engine())


# ============================ loader ============================

class EventLoaderTest(unittest.TestCase):
    def test_event_case_file_loads(self):
        st = load_strategy_file(str(CASES / "strategy_ma_event.py"))
        self.assertEqual(st.mode, "event")
        self.assertEqual(st.warmup, 20)
        self.assertEqual(st.params, {"fast": 5, "slow": 15})
        self.assertIsNone(st.main)
        self.assertTrue(callable(st.on_bar))
        self.assertTrue(callable(st.init))

    def test_on_bar_missing(self):
        src = ('STRATEGY_MODE = "event"\nNAME = "x"\nWARMUP = 0\nPARAMS = {}\n'
               "def init(params, ctx):\n    return {}\n")
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "ON_BAR_MISSING")
        self.assertEqual(check_source(src)[0]["code"], "ON_BAR_MISSING")

    def test_main_forbidden(self):
        src = _src("return 0.0", main="def main(params, ohlcv):\n    return {}")
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "MAIN_FORBIDDEN_IN_EVENT")
        self.assertEqual(check_source(src)[0]["code"], "MAIN_FORBIDDEN_IN_EVENT")

    def test_init_optional(self):
        st = load_strategy(_src("return 0.0"))
        self.assertIsNone(st.init)

    def test_on_bar_signature(self):
        src = ('STRATEGY_MODE = "event"\nNAME = "x"\nWARMUP = 0\nPARAMS = {}\n'
               "def on_bar(state, bar):\n    return 0.0\n")
        errors = check_source(src)
        self.assertEqual(errors[0]["code"], "STRATEGY_INVALID")
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "STRATEGY_INVALID")

    def test_init_signature(self):
        src = _src("return 0.0", init="def init(params):\n    return {}")
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "STRATEGY_INVALID")

    def test_mode_mismatch(self):
        src = ('STRATEGY_MODE = "tick"\nNAME = "x"\nWARMUP = 0\nPARAMS = {}\n'
               "def on_bar(state, bar, ctx):\n    return 0.0\n")
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "MODE_MISMATCH")

    def test_ast_check_does_not_execute(self):
        src = _src("return 0.0") + '\nraise RuntimeError("boom")\n'
        self.assertEqual(check_source(src), [])
        with self.assertRaises(AKError) as cm:
            load_strategy(src)
        self.assertEqual(cm.exception.code, "STRATEGY_INVALID")

    def test_describe_source_mode(self):
        info = describe_source(_src("return 0.0"))
        self.assertEqual(info["mode"], "event")
        self.assertEqual(info["errors"], [])


# ============================ ctx ============================

class ContextTest(unittest.TestCase):
    def _ctx(self, t=2, equity=1000.0, params=None, entry_index=None):
        bars = _bars(6)
        matcher = MatchingEngine(initial_cash=1000.0, fee_bps=0.0, slippage_bps=0.0)
        return EventContext(bars, t, matcher, equity, params or {"n": 2}, entry_index), bars

    def test_history_tail_window(self):
        ctx, bars = self._ctx(t=2)
        self.assertEqual([b["close"] for b in ctx.history(2)],
                         [bars[1]["close"], bars[2]["close"]])
        self.assertEqual(len(ctx.history(10)), 3)
        self.assertEqual(ctx.history(0), [])
        self.assertEqual(list(ctx.history(1)[0]), ["timestamp", "open", "high", "low",
                                                   "close", "volume"])
        only_close = ctx.history(2, ["close"])
        self.assertEqual(only_close, [{"close": bars[1]["close"]},
                                      {"close": bars[2]["close"]}])
        self.assertEqual(ctx.history(2, "close")[0], {"close": bars[1]["close"]})

    def test_history_edges(self):
        ctx, _ = self._ctx(t=2)
        with self.assertRaises(AKError) as cm:
            ctx.history(-1)
        self.assertEqual(cm.exception.code, "INPUT_INVALID")
        with self.assertRaises(AKError) as cm:
            ctx.history(2, ["nope"])
        self.assertEqual(cm.exception.code, "INPUT_INVALID")
        with self.assertRaises(AKError) as cm:
            ctx.history("3")
        self.assertEqual(cm.exception.code, "INPUT_INVALID")

    def test_history_before_first_bar(self):
        ctx, _ = self._ctx(t=-1)
        self.assertEqual(ctx.history(5), [])
        self.assertEqual(ctx.t, -1)
        self.assertEqual(ctx.equity, 1000.0)
        self.assertEqual(ctx.position,
                         {"weight": 0.0, "entry_price": None, "bars_held": 0})

    def test_read_only(self):
        ctx, _ = self._ctx(t=2)
        with self.assertRaises(AttributeError):
            ctx.t = 9
        with self.assertRaises(AttributeError):
            ctx.cash = 1.0
        with self.assertRaises(AttributeError):
            ctx.new_attr = 1
        with self.assertRaises(AttributeError):
            del ctx.t
        ctx.params["n"] = 99
        self.assertEqual(ctx.params["n"], 2)
        self.assertEqual(ctx.params, {"n": 2})
        got = ctx.history(3)
        got[0]["close"] = -1.0
        self.assertEqual(ctx.history(3)[0]["close"], 100.0)
        pos = ctx.position
        pos["weight"] = 123.0
        self.assertEqual(ctx.position["weight"], 0.0)

    def test_position_view(self):
        bars = _bars(6)
        matcher = MatchingEngine(initial_cash=1000.0, fee_bps=0.0, slippage_bps=0.0)
        matcher.execute_target(bars[0], 1.0, 1000.0)
        ctx = EventContext(bars, 1, matcher, matcher.equity(bars[1]["close"]),
                           {"n": 2}, 0)
        pos = ctx.position
        self.assertAlmostEqual(pos["weight"], 1.0)
        self.assertAlmostEqual(pos["entry_price"], 100.0)
        self.assertEqual(pos["bars_held"], 1)
        self.assertAlmostEqual(ctx.cash, 0.0)
        self.assertAlmostEqual(ctx.equity, matcher.equity(bars[1]["close"]))

    def test_position_flat(self):
        bars = _bars(3)
        matcher = MatchingEngine(initial_cash=1000.0)
        ctx = EventContext(bars, 2, matcher, 1000.0, {}, None)
        self.assertEqual(ctx.position,
                         {"weight": 0.0, "entry_price": None, "bars_held": 0})


# ============================ warmup / state ============================

class WarmupTest(unittest.TestCase):
    def test_warmup_suppresses_targets(self):
        src = _src("return 1.0", warmup=3)
        bars = _bars(8)
        res = _run(src, bars)
        # 第 3 根收盘决策，第 4 根开盘成交
        self.assertEqual(res.fills[0]["time"], bars[4]["timestamp"])
        self.assertEqual(len(res.equity["values"]), len(bars) - 3)
        self.assertEqual(res.equity["times"][0], bars[3]["timestamp"])

    def test_no_warmup_executes_next_open(self):
        src = _src("return 1.0", warmup=0)
        bars = _bars(5)
        res = _run(src, bars)
        self.assertEqual(res.fills[0]["time"], bars[1]["timestamp"])

    def test_state_built_from_bar_zero(self):
        # count 在 on_bar 里自增；只有从 bar0 起逐根调用，bar5 时才会到 6
        src = _src('state["n"] = state.get("n", 0) + 1\n'
                   'return 1.0 if state["n"] == 6 else 0.0', warmup=3)
        bars = _bars(9)
        res = _run(src, bars)
        self.assertTrue(res.fills)
        self.assertEqual(res.fills[0]["time"], bars[6]["timestamp"])

    def test_state_init_defaults_to_empty(self):
        src = _src('state["seen"] = ctx.t\nreturn 0.0')
        res = _run(src)
        self.assertEqual(res.status, "no_signals")


class StateTest(unittest.TestCase):
    def _expect(self, src, code):
        with self.assertRaises(AKError) as cm:
            _run(src)
        self.assertEqual(cm.exception.code, code, cm.exception.message)

    def test_init_bad_return(self):
        self._expect(_src("return 0.0", init="def init(params, ctx):\n    return []"),
                     "INIT_BAD_RETURN")
        self._expect(_src("return 0.0", init="def init(params, ctx):\n    return 3"),
                     "INIT_BAD_RETURN")

    def test_init_state_not_json(self):
        self._expect(_src("return 0.0", init='def init(params, ctx):\n    return {"s": {1}}'),
                     "STATE_NOT_JSON")

    def test_state_nan_at_end(self):
        self._expect(_src('state["bad"] = float("nan")\nreturn 0.0'), "STATE_NOT_JSON")

    def test_state_tuple(self):
        self._expect(_src('state["x"] = (1, 2)\nreturn 0.0'), "STATE_NOT_JSON")

    def test_state_non_str_key(self):
        self._expect(_src('state[1] = 2\nreturn 0.0'), "STATE_NOT_JSON")

    def test_state_object(self):
        self._expect(_src('state["x"] = object()\nreturn 0.0'), "STATE_NOT_JSON")

    def test_state_nested_ok(self):
        src = _src('state["x"] = {"a": [1, 2.5, True, None, "s"]}\nreturn 0.0')
        res = _run(src)
        self.assertEqual(res.status, "no_signals")

    def test_ensure_state_json_direct(self):
        ensure_state_json({"a": [1, {"b": None}], "c": 2.5})
        with self.assertRaises(AKError) as cm:
            ensure_state_json({"a": float("inf")})
        self.assertEqual(cm.exception.code, "STATE_NOT_JSON")
        with self.assertRaises(AKError) as cm:
            ensure_state_json([1, 2])
        self.assertEqual(cm.exception.code, "STATE_NOT_JSON")


# ============================ 状态机样例（移动止损） ============================

MOVE_STOP = _src(
    """
    trail = ctx.params["trail"]
    c = bar["close"]
    if state["side"] == 0:
        state["side"] = 1
        state["extreme"] = c
        return 1.0
    if state["side"] > 0:
        if c > state["extreme"]:
            state["extreme"] = c
        if c <= state["extreme"] * (1 - trail):
            state["side"] = -1
            state["extreme"] = c
            return -1.0
        return 1.0
    if c < state["extreme"]:
        state["extreme"] = c
    if c >= state["extreme"] * (1 + trail):
        state["side"] = 1
        state["extreme"] = c
        return 1.0
    return -1.0
    """,
    params='{"trail": 0.1}',
    init='def init(params, ctx):\n    return {"side": 0, "extreme": 0.0}',
)


class StateMachineTest(unittest.TestCase):
    """state 记 side/extreme 的移动止损：覆盖跳空出场与同根反手。"""

    def test_hand_computed_fills(self):
        closes = [100, 100, 110, 120, 108, 95, 90, 100, 111, 100]
        opens = [100, 100, 100, 110, 120, 90, 95, 90, 100, 111]
        bars = bars_from_closes(closes, opens=opens)
        # 容差 1.0 关掉持仓期的分数再平衡，手算序列才是逐笔精确的
        res = _run(MOVE_STOP, bars, rebalance_tolerance=1.0)

        want = [
            (1, "buy", 10.0, 100.0, "signal"),
            (5, "sell", -10.0, 90.0, "flip"),      # 跳空 108→90，先平多
            (5, "sell", -10.0, 90.0, "signal"),    # 同根反手开空
            (8, "buy", 10.0, 100.0, "flip"),       # 空头回补
            (8, "buy", 8.0, 100.0, "signal"),      # 同根反手开多
            (9, "sell", -8.0, 100.0, "end_of_backtest"),
        ]
        got = [(f["index"], f["action"], round(f["signed_qty"], 9),
                round(f["price"], 9), f["reason"]) for f in res.fills]
        self.assertEqual(got, want)
        self.assertEqual(res.status, "completed_trades")
        want_trades = [
            ("long", 100.0, 90.0, 10.0, -100.0),
            ("short", 90.0, 100.0, 10.0, -100.0),
            ("long", 100.0, 100.0, 8.0, 0.0),
        ]
        got_trades = [(t["side"], round(t["entry_price"], 9), round(t["exit_price"], 9),
                       round(t["size"], 9), round(t["pnl"], 9)) for t in res.trades]
        self.assertEqual(got_trades, want_trades)
        self.assertAlmostEqual(res.stats["final_value"], 800.0)
        self.assertAlmostEqual(res.stats["total_fees"], 0.0)

    def test_state_shape_validated(self):
        # 同一策略的 state 只含 int/float，跑完不报 STATE_NOT_JSON
        res = _run(MOVE_STOP, _bars(6), rebalance_tolerance=1.0)
        self.assertIn(res.status, ("completed_trades", "open_position_only", "no_signals"))


# ============================ target 返回 ============================

class ReturnTest(unittest.TestCase):
    def _expect(self, body, code="ON_BAR_BAD_RETURN"):
        with self.assertRaises(AKError) as cm:
            _run(_src(body))
        self.assertEqual(cm.exception.code, code, cm.exception.message)

    def test_none(self):
        self._expect("return None")

    def test_dict_without_target(self):
        self._expect('return {"reason": "x"}')

    def test_non_numeric(self):
        self._expect('return "x"')

    def test_nan(self):
        self._expect('return float("nan")')

    def test_infinite(self):
        self._expect('return float("inf")')

    def test_bool(self):
        self._expect("return True")

    def test_bare_float_allowed(self):
        res = _run(_src("return 1.0"))
        self.assertTrue(res.trades)

    def test_dict_reason_allowed(self):
        src = _src('return {"target": 1.0, "reason": "golden"}')
        res = _run(src)
        self.assertEqual(res.trades[0]["entry_reason"], "golden")

    def test_clipping(self):
        res = _run(_src("return 3.0 if ctx.t == 0 else 0.0"))
        self.assertIn("target_clipped=1", res.warnings)
        self.assertLessEqual(max(t["notional"] for t in res.trades), 1000.0)

    def test_direction_clamped(self):
        res = _run(_src("return -1.0 if ctx.t == 0 else 0.0"), direction="long_only")
        self.assertIn("direction_clamped=1", res.warnings)

    def test_normalize_reason_coerced(self):
        target, reason, clipped = normalize_event_return({"target": 2, "reason": 3}, 0)
        self.assertEqual((target, reason, clipped), (1.0, "3", True))


# ============================ 引擎分派 ============================

class DispatchTest(unittest.TestCase):
    def _spec(self, strategy: str, mode=None) -> dict:
        spec = {
            "api": 1,
            "engine": "builtin",
            "bars": {"path": str(CASES / "btc_1d_200.csv"), "format": "csv"},
            "strategy": {"path": str(CASES / strategy)},
            "run": {"initial_cash": 10000, "fee_bps": 5, "slippage_bps": 5},
            "timeframe": "1d",
        }
        if mode is not None:
            spec["mode"] = mode
        return spec

    def test_caps_event(self):
        self.assertTrue(get_engine("builtin").caps["event"])

    def test_mode_from_strategy_when_omitted(self):
        req = build_request(self._spec("strategy_ma_event.py"))
        self.assertIsNone(req.mode)
        res = get_engine("builtin").run(req)
        self.assertTrue(res.fills)

    def test_explicit_mode_mismatch(self):
        for strategy, mode in (("strategy_ma.py", "event"),
                               ("strategy_ma_event.py", "signal")):
            with self.subTest(strategy=strategy):
                req = build_request(self._spec(strategy, mode))
                with self.assertRaises(AKError) as cm:
                    get_engine("builtin").run(req)
                self.assertEqual(cm.exception.code, "MODE_MISMATCH")

    def test_request_mode_validated(self):
        with self.assertRaises(AKError) as cm:
            build_request(self._spec("strategy_ma.py", "tick")).validate()
        self.assertEqual(cm.exception.code, "INPUT_INVALID")


# ============================ 跨范式 CLI 对账 ============================

def _cli_cmd():
    if EXE.exists():
        return [str(EXE)]
    return [sys.executable, "-m", "agentkline_engine.cli"]


def _run_cli(args, *, stdin=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(_cli_cmd() + args, input=stdin, capture_output=True, text=True,
                          cwd=str(ROOT), env=env, timeout=120)


def _parse(proc) -> dict:
    lines = proc.stdout.splitlines()
    if not lines or lines[0] != "__AK_RESULT__":
        raise AssertionError(f"缺少哨兵: {proc.stdout[:200]!r}")
    return json.loads(lines[1])


def _cli_spec(strategy: str, mode: str, *, direction: str = "long_only",
              params=None, protection=None, extra_run=None) -> dict:
    run = {"initial_cash": 100000, "fee_bps": 5, "slippage_bps": 5,
           "direction": direction, "params": params or {}}
    if protection:
        run["protection"] = protection
    run.update(extra_run or {})
    return {
        "api": 1,
        "engine": "builtin",
        "mode": mode,
        "bars": {"path": str(CASES / "stock_1d_500.csv"), "format": "csv"},
        "strategy": {"path": str(CASES / strategy)},
        "run": run,
        "timeframe": "1d",
    }


class GoldenStatsTest(unittest.TestCase):
    """golden 统计回归（LEAN ExpectedStatistics 口径）：固定数据/参数/常量，
    防止“改 A 坏 B”；与 CrossParadigmTest 互补——那边验等价，这边验绝对值。"""

    def test_expected_statistics(self):
        p = _run_cli(["run", "--stdin"], stdin=json.dumps(
            _cli_spec("strategy_ma_event.py", "event")))
        self.assertEqual(p.returncode, 0, p.stderr)
        r = _parse(p)
        st = r["stats"]
        self.assertEqual(r["mode"], "event")
        self.assertEqual(len(r["fills"]), 32)
        self.assertEqual(len(r["trades"]), 16)
        self.assertAlmostEqual(st["final_value"], 127659.621785, places=6)
        self.assertAlmostEqual(st["total_fees"], 1853.701229, places=6)


class CrossParadigmTest(unittest.TestCase):
    """同数据同参数下 signal / event 的逐笔结果必须完全一致。"""

    CASES_ = (
        ("long_only", {}, None, None),
        ("both", {"fast": 7, "slow": 21}, None, None),
        ("both", {"fast": 9, "slow": 30},
         {"stop_loss_pct": 0.03, "take_profit_pct": 0.06}, None),
        ("both", {}, None,
         {"eval_start": 120, "start_flat": True, "flatten": False}),
    )

    def _pair(self, direction, params, protection, extra_run):
        p_signal = _run_cli(["run", "--stdin"], stdin=json.dumps(
            _cli_spec("strategy_ma.py", "signal", direction=direction,
                      params=params, protection=protection, extra_run=extra_run)))
        p_event = _run_cli(["run", "--stdin"], stdin=json.dumps(
            _cli_spec("strategy_ma_event.py", "event", direction=direction,
                      params=params, protection=protection, extra_run=extra_run)))
        self.assertEqual(p_signal.returncode, 0, p_signal.stderr)
        self.assertEqual(p_event.returncode, 0, p_event.stderr)
        return _parse(p_signal), _parse(p_event)

    def test_fills_trades_equity_match(self):
        for direction, params, protection, extra_run in self.CASES_:
            with self.subTest(direction=direction, params=params, protection=protection,
                              extra_run=extra_run):
                sig, evt = self._pair(direction, params, protection, extra_run)
                self.assertTrue(sig["fills"])
                self.assertEqual(len(sig["fills"]), len(evt["fills"]))
                self.assertEqual(len(sig["trades"]), len(evt["trades"]))
                for key in ("status", "bars", "fills", "trades", "equity", "stats",
                            "warnings", "assumptions"):
                    self.assertEqual(sig[key], evt[key], f"{key} 不一致")
                # 成交笔数/方向/价/费/逐点权益/期末资金逐项核对
                for a, b in zip(sig["fills"], evt["fills"]):
                    self.assertEqual((a["time"], a["index"], a["action"], a["signed_qty"],
                                      a["price"], a["fee"], a["reason"]),
                                     (b["time"], b["index"], b["action"], b["signed_qty"],
                                      b["price"], b["fee"], b["reason"]))
                self.assertEqual(sig["equity"]["values"], evt["equity"]["values"])
                self.assertEqual(sig["stats"]["final_value"], evt["stats"]["final_value"])
                self.assertEqual(sig["stats"]["total_fees"], evt["stats"]["total_fees"])

    def test_entire_payload_identical(self):
        sig, evt = self._pair("both", {"fast": 5, "slow": 15}, None, None)
        self.assertEqual(sig["mode"], "signal")
        self.assertEqual(evt["mode"], "event")
        # mode 是唯一按范式不同的字段；撮合/权益/统计必须逐字段一致
        sig.pop("mode")
        evt.pop("mode")
        assert_deep_equal(self, evt, sig, msg="event vs signal")

    def test_cli_mode_override(self):
        spec = _cli_spec("strategy_ma_event.py", "signal")
        p = _run_cli(["run", "--stdin", "--mode", "event"], stdin=json.dumps(spec))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(_parse(p)["fills"])

        spec = _cli_spec("strategy_ma_event.py", "event")
        p = _run_cli(["run", "--stdin", "--mode", "signal"], stdin=json.dumps(spec))
        self.assertEqual(p.returncode, 2)
        self.assertEqual(_parse(p)["error"]["code"], "MODE_MISMATCH")

    def test_validate_event_strategy(self):
        p = _run_cli(["validate-strategy", str(CASES / "strategy_ma_event.py"), "--json"])
        self.assertEqual(p.returncode, 0, p.stderr)
        payload = _parse(p)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "event")

    def test_signal_subcommand_rejects_event(self):
        spec = {"api": 1, "bars": _bars(5), "strategy": {"path": str(CASES / "strategy_ma_event.py")},
                "run": {}}
        p = _run_cli(["signal", "--stdin"], stdin=json.dumps(spec))
        self.assertEqual(p.returncode, 2)
        self.assertEqual(_parse(p)["error"]["code"], "MODE_MISMATCH")


if __name__ == "__main__":
    unittest.main()
