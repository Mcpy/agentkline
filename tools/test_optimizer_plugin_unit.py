#!/usr/bin/env python3
"""优化器插件契约单测（0.6.6）：kind/元数据/保存校验/自定义 PARAMS/rank/连续候选。"""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentkline.core.service import AgentKlineService  # noqa: E402

ok = 0
bad = []


def check(name, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        bad.append(name)
        print(f"  ❌ {name} {detail}")


def wait(svc, job_id, timeout=60):
    deadline = time.time() + timeout
    st = {}
    while time.time() < deadline:
        st = svc.get_optimization(job_id)
        if st.get("status") != "running":
            return st
        time.sleep(0.1)
    return st


MULTI = '''OPTIMIZER_API = 1
NAME = "测试加权"
DESC = "multi"
PARAMS = {"w_sharpe": 0.6, "w_return": 0.4}
PARAM_META = {"w_sharpe": {"type": "float", "min": 0, "max": 1},
              "w_return": {"type": "float", "min": 0, "max": 1}}
CAPS = {"continuous": False, "multi_objective": True,
        "requires_full_space": False, "custom_score": False}

def init(ctx):
    return {"i": 0, "combos": [{"fast": 5, "slow": 30}, {"fast": 10, "slow": 60}]}

def ask(state, ctx):
    i = state["i"]
    if i >= len(state["combos"]):
        return None
    state["i"] = i + 1
    return state["combos"][i]

def rank(state, ctx, trials, phase):
    ws = float(ctx["params"].get("w_sharpe") or 0)
    wr = float(ctx["params"].get("w_return") or 0)
    def val(t):
        s = (t.get("oos_stats") if phase == "oos" else t.get("is_stats")) or {}
        return ws * float(s.get("sharpe") or 0) + wr * float(s.get("total_return") or 0)
    return [i for i, _ in sorted(enumerate(trials), key=lambda x: -val(x[1]))]
'''

EDGE = '''OPTIMIZER_API = 1
NAME = "边界"
DESC = "continuous/out-of-space"
PARAMS = {}
PARAM_META = {}
CAPS = {"continuous": True, "multi_objective": False,
        "requires_full_space": False, "custom_score": False}

def init(ctx):
    return {"i": 0}

def ask(state, ctx):
    i = state["i"]
    state["i"] = i + 1
    if i == 0:
        return {"fast": 7}
    if i == 1:
        return {"fast": 999}
    return None
'''


def main():
    with tempfile.TemporaryDirectory() as d:
        svc = AgentKlineService(d, data_dir=None)
        opts = svc.script_engine.list_optimizers()
        ids = {o["id"] for o in opts}
        check("内置优化器三件", {"optimizer/grid", "optimizer/random", "optimizer/bayes"} <= ids,
              str(ids))
        check("内置优化器声明 API", all(o.get("api") == 1 for o in opts
                                      if o["source"] == "builtin"), str(opts)[:200])

        r = svc.script_engine.save_script("optimizer/no_ask", """OPTIMIZER_API = 1
NAME='x'
""")
        check("缺 ask 保存即拒", "SAVE_OPTIMIZER_ASK" in str(r.get("error")), str(r))
        r = svc.script_engine.save_script(
            "optimizer/no_api", """NAME='x'
def ask(state, ctx): return None
""")
        check("缺 OPTIMIZER_API 保存即拒", "SAVE_OPTIMIZER_API" in str(r.get("error")), str(r))

        check("自定义多目标保存", svc.script_engine.save_script(
            "optimizer/unit_multi", MULTI).get("ok"))
        check("自定义连续/越界保存", svc.script_engine.save_script(
            "optimizer/unit_edge", EDGE).get("ok"))

        svc.create_board("t1", None, None, "BT/USDT", "datasource/mock_btc", {"days": 120})
        r = svc.run_optimization(
            "t1", "1d", script="strategy/ma_cross",
            space={"fast": [5, 10], "slow": [30, 60]},
            method="optimizer/unit_multi",
            objective={"metrics": ["sharpe", "total_return"]},
            optimizer_params={"w_sharpe": 0.9, "w_return": 0.1},
            budget={"max_runs": 2, "max_seconds": 120},
            holdout={"ratio": 0, "top_k": 1}, seed=2, limit=300)
        check("自定义优化器启动", r.get("status") == "ok" and r.get("total") == 2, str(r)[:200])
        st = wait(svc, r.get("job_id"))
        check("自定义 rank 生效", st.get("status") == "done"
              and st.get("ranked_by") == "optimizer"
              and (st.get("optimizer") or {}).get("id") == "optimizer/unit_multi", str(st)[:240])
        check("优化器参数覆盖/回显",
              st.get("optimizer_params") == {"w_sharpe": 0.9, "w_return": 0.1},
              str(st.get("optimizer_params")))
        check("多目标试次无强制单指标分",
              all(t.get("score") is None for t in st.get("trials") or []),
              str(st.get("trials"))[:240])

        r = svc.run_optimization(
            "t1", "1d", script="strategy/ma_cross", space={"fast": [5, 10]},
            method="optimizer/unit_edge", budget={"max_runs": 2, "max_seconds": 120},
            holdout={"ratio": 0, "top_k": 1}, seed=1, limit=300)
        st = wait(svc, r.get("job_id"))
        trials = st.get("trials") or []
        check("连续候选可落在离散空间之外", len(trials) >= 1
              and (trials[0].get("params") or {}).get("fast") == 7, str(trials)[:200])
        check("非法候选记 invalid 且不炸作业", st.get("status") == "done"
              and any(t.get("status") == "invalid" for t in trials)
              and st.get("done") == 2, str(st)[:240])

    print(f"\nOptimizer plugin: {ok} passed, {len(bad)} failed")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
