#!/usr/bin/env python3
"""v0.6.7 稳健性单测：walk-forward 切窗/参数邻域/报告落盘。

    .venv/bin/python tools/test_robustness_unit.py
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentkline.core import optimizer as opt
from agentkline.core.service import AgentKlineService

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


def test_folds():
    wf, err = opt.build_walk_forward(1400, {"folds": 5, "is_ratio": 0.75})
    check("5 折 3:1 切分", err is None and wf["fold_count"] == 5
          and wf["is_bars"] == 525 and wf["oos_bars"] == 175
          and wf["windows"][-1]["oos_end"] == 1400, f"{err} {wf}")
    wf, err = opt.build_walk_forward(300, {"folds": 5, "is_ratio": 0.75})
    check("5 折在短数据上自动收口", err is None and wf["fold_count"] == 5
          and wf["oos_bars"] >= opt.MIN_EVAL_BARS, f"{err} {wf}")
    _, err = opt.build_walk_forward(80, {"folds": 3, "is_ratio": 0.75})
    check("数据不足明确拒绝", "WF_INSUFFICIENT_BARS" in str(err), str(err))
    wf, err = opt.build_walk_forward(120, {"folds": 5, "is_ratio": 0.75})
    check("数据不足自动降折", err is None and wf["fold_count"] == 3
          and any(w["code"] == "WF_FOLDS_REDUCED" for w in wf["warnings"]),
          f"{err} {wf}")
    wf, err = opt.build_walk_forward(400, {"folds": 3, "is_ratio": 0.75, "step": 100})
    check("自定义 step 过大给空档警告", err is None
          and any(w["code"] == "WF_STEP_GAP" for w in wf["warnings"]), f"{err} {wf}")
    wf, err = opt.build_walk_forward(300, {"folds": 3, "is_ratio": 0.75,
                                            "window": "anchored"})
    check("锚定窗口 IS 起点固定", err is None
          and wf["windows"][0]["is_start"] == 0
          and wf["windows"][1]["is_start"] == 0
          and wf["windows"][2]["is_end"] > wf["windows"][0]["is_end"]
          and wf["windows"][1]["is_bars"] > wf["windows"][0]["is_bars"], f"{err} {wf}")


def test_neighbors():
    values = {"fast": [5, 10, 15, 20], "slow": [20, 30, 40, 50]}
    meta = {"fast": {"type": "int", "step": 1}, "slow": {"type": "int", "step": 1}}
    got, err = opt.build_neighbors(values, {"fast": 10, "slow": 30}, meta,
                                   {"scope": "one_at_a_time", "max_runs": 24})
    check("OAT 邻域含中心+两侧", err is None and got[0] == {"fast": 10, "slow": 30}
          and {"fast": 5, "slow": 30} in got and {"fast": 15, "slow": 30} in got,
          f"{err} {got}")
    got, err = opt.build_neighbors(values, {"fast": 10, "slow": 30}, meta,
                                   {"scope": "top2", "max_runs": 24})
    check("top2 二维网格", err is None and len(got) == 9, f"{err} {got}")
    meta2 = {"x": {"type": "float", "step": 0.01}}
    got, err = opt.build_neighbors({"x": [1.0, 1.1, 1.2, 1.3]},
                                   {"x": 1.1}, meta2,
                                   {"mode": "percent", "scope": "one_at_a_time"})
    check("连续参数 ±10% 吸附离散值", err is None and len(got) == 3,
          f"{err} {got}")
    _, err = opt.parse_stability({"scope": "bad"})
    check("邻域配置校验", "STABILITY_CONFIG_INVALID" in str(err), str(err))


def test_stability():
    center = {"a": 1}
    runs = [{"params": {"a": 1}, "oos_score": 1.0},
            {"params": {"a": 2}, "oos_score": 0.9},
            {"params": {"a": 3}, "oos_score": 0.8}]
    s = opt.stability_summary(runs, center, 0.5, 0.8)
    check("高原判定", s["pass_ratio"] == 1.0 and not s["isolated_peak"], str(s))
    runs = [{"params": {"a": 1}, "oos_score": 1.0},
            {"params": {"a": 2}, "oos_score": -1.0},
            {"params": {"a": 3}, "oos_score": -2.0}]
    s = opt.stability_summary(runs, center, 0.5, 0.8)
    check("孤峰判定", s["pass_ratio"] < 0.5 and s["isolated_peak"]
          and any(w["code"] == "PARAM_ISOLATED_PEAK" for w in s["warnings"]), str(s))


def test_service_persistence():
    tmp = Path(tempfile.mkdtemp(prefix="ak_robust_"))
    try:
        svc = AgentKlineService(str(ROOT / "scripts"), data_dir=str(tmp))
        svc.create_board("t1", None, None, "BT/USDT", "datasource/mock_btc",
                         {"days": 300})
        r = svc.run_optimization(
            "t1", "1d", script="strategy/ma_cross",
            space={"fast": [5, 10], "slow": [30, 60]}, method="grid",
            objective={"metric": "sharpe"}, budget={"max_runs": 4, "max_seconds": 120},
            mode="walk_forward",
            walk_forward={"folds": 3, "window": "rolling", "is_ratio": 0.75},
            stability={"enabled": True, "max_runs": 8}, seed=2, limit=300)
        job = r.get("job_id")
        st = {}
        for _ in range(120):
            st = svc.get_optimization(job) if job else {}
            if st.get("status") != "running":
                break
            time.sleep(0.2)
        check("服务 WF 跑完", st.get("status") == "done" and len(st.get("folds") or []) == 3
              and len(st.get("registered_result_ids") or []) == 3, str(st)[:220])
        check("服务 WF 汇总+邻域", (st.get("walk_forward") or {}).get("summary", {})
              .get("valid_folds") == 3 and (st.get("stability") or {}).get("runs"),
              str(st.get("stability"))[:180])
        rows = svc.list_optimizations("t1").get("optimizations") or []
        check("历史列表可读", rows and rows[0].get("job_id") == job, str(rows)[:180])
        svc.store.close()
        svc2 = AgentKlineService(str(ROOT / "scripts"), data_dir=str(tmp))
        st2 = svc2.get_optimization(job)
        check("重启后报告仍在", st2.get("status") == "done" and st2.get("persisted"),
              str(st2)[:180])
        svc2.store.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("== 切窗 ==")
    test_folds()
    print("== 邻域 ==")
    test_neighbors()
    print("== 稳定分 ==")
    test_stability()
    print("== 服务/落盘 ==")
    test_service_persistence()
    print(f"\nRobustness: {ok} passed, {len(bad)} failed")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
