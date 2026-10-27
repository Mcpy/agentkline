#!/usr/bin/env python3
"""参数寻优单测（v0.6.5）：空间/目标/约束、三种搜索器、样本外切分、作业登记、方案哈希。

    python tools/test_optimizer_unit.py
"""
import json
import random
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentkline.core import optimizer as opt
from agentkline.core.service import AgentKlineService
from agentkline.core.store import Store

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


def _svc(data_dir=None):
    svc = AgentKlineService(str(ROOT / "scripts"), data_dir=data_dir)
    svc.create_board("t1", None, None, "BT/USDT", "datasource/mock_btc", {"days": 300})
    return svc


def _wait(svc, job_id, timeout=120):
    deadline = time.time() + timeout
    st = {}
    while time.time() < deadline:
        st = svc.get_optimization(job_id)
        if st.get("status") != "running":
            return st
        time.sleep(0.2)
    return st


def test_pure():
    info = {"params": {"fast": 5, "slow": 30, "flag": False, "name": "x"},
            "param_meta": {"fast": {"type": "int", "min": 1, "max": 50},
                           "slow": {"type": "int", "min": 2, "max": 200},
                           "flag": {"type": "bool"}, "name": {"type": "str"}}}
    sp, err = opt.parse_space(info, {"fast": {"min": 5, "max": 15, "step": 5},
                                     "slow": {"values": [20, 30, 40]}})
    check("range + values 展开", err is None and sp["values"] == {"fast": [5, 10, 15],
                                                                  "slow": [20, 30, 40]}
          and sp["size"] == 9, f"{err} {sp}")
    sp2, err2 = opt.parse_space(info, {"fast": [5, 5, "10"]})
    check("候选值去重/收敛", err2 is None and sp2["values"]["fast"] == [5, 10], str(err2))
    _, err3 = opt.parse_space(info, {"nope": [1]})
    check("未知参数被拒", "OPTIMIZE_SPACE_INVALID" in str(err3), str(err3))
    _, err4 = opt.parse_space(info, {"fast": {"min": 5}})
    check("range 缺 max 被拒", "需要 min 和 max" in str(err4), str(err4))
    _, err5 = opt.parse_space(info, {"fast": [0]})
    check("越界参数被拒", "下限" in str(err5), str(err5))
    _, err6 = opt.parse_space(info, {"fast": {"min": 0, "max": 5000, "step": 1}})
    check("候选值过多被拒", "TOO_LARGE" in str(err6), str(err6))

    obj, err = opt.parse_objective({"metric": "sharpe"})
    check("目标默认方向", err is None and obj == {"metric": "sharpe", "direction": "max"}, str(err))
    _, err = opt.parse_objective({"metric": "nope"})
    check("未知目标指标被拒", "OBJECTIVE_INVALID" in str(err), str(err))
    cons, err = opt.parse_constraints({"min_trades": 3, "max_drawdown": 0.3})
    check("约束解析", err is None and cons == {"min_trades": 3, "max_drawdown": 0.3}, str(err))
    _, err = opt.parse_constraints({"max_drawdown": 1.5})
    check("约束越界被拒", "CONSTRAINT_INVALID" in str(err), str(err))

    good = {"trade_count": 5, "sharpe": 1.2, "max_drawdown": -0.2}
    s = opt.score_stats(good, {"metric": "sharpe", "direction": "max"}, {"min_trades": 3})
    check("评分 ok", s["status"] == "ok" and abs(s["score"] - 1.2) < 1e-9, str(s))
    s = opt.score_stats(good, {"metric": "sharpe", "direction": "max"}, {"min_trades": 9})
    check("交易数不足 rejected", s["status"] == "rejected" and "MIN_TRADES" in s["reason"], str(s))
    s = opt.score_stats(good, {"metric": "sharpe", "direction": "max"}, {"max_drawdown": 0.1})
    check("回撤超限 rejected", s["status"] == "rejected" and "MAX_DRAWDOWN" in s["reason"], str(s))
    s = opt.score_stats({"trade_count": 5}, {"metric": "sharpe", "direction": "max"}, {})
    check("指标缺失 invalid", s["status"] == "invalid", str(s))
    s = opt.score_stats(good, {"metric": "sharpe", "direction": "min"}, {})
    check("min 方向取负", s["score"] == -1.2, str(s))

    grid, err = opt.expand_grid({"a": [1, 2], "b": [3, 4]}, 10)
    check("网格全组合", err is None and len(grid) == 4, str(err))
    _, err = opt.expand_grid({"a": list(range(20))}, 10)
    check("网格超预算被拒", "OPTIMIZE_BUDGET" in str(err), str(err))

    is_n, oos_n, err = opt.split_eval_bars(100, 0.3)
    check("样本外 70/30 切分", err is None and (is_n, oos_n) == (70, 30), str(err))
    _, _, err = opt.split_eval_bars(30, 0.3)
    check("样本太短被拒", "TOO_SMALL" in str(err), str(err))
    is_n, oos_n, err = opt.split_eval_bars(100, 0)
    check("ratio=0 不切", err is None and (is_n, oos_n) == (100, 0), str(err))

    values = {"a": [1, 2, 3], "b": [10, 20]}
    rng = random.Random(3)
    tried = set()
    got = []
    for _ in range(10):
        c = opt.next_random(values, rng, tried)
        if c is None:
            break
        tried.add(opt._key(c))
        got.append(opt._key(c))
    check("随机采样不重复/空间用尽返回 None",
          len(got) == 6 and len(set(got)) == 6 and opt.next_random(values, rng, tried) is None,
          str(got))

    obs = [{"params": {"a": 1, "b": 10}, "score": 3.0},
           {"params": {"a": 1, "b": 20}, "score": 2.0},
           {"params": {"a": 2, "b": 10}, "score": 1.0},
           {"params": {"a": 3, "b": 20}, "score": 0.1}]
    c1 = opt.propose_tpe(values, obs, random.Random(9), set())
    c2 = opt.propose_tpe(values, obs, random.Random(9), set())
    check("TPE 可复现且落在空间内",
          c1 == c2 and c1 in [{"a": a, "b": b} for a in values["a"] for b in values["b"]],
          f"{c1} {c2}")

    over = opt.overfit_check({"sharpe": 1.0}, {"sharpe": 0.2},
                             {"metric": "sharpe", "direction": "max"})
    codes = {w["code"] for w in over["warnings"]}
    check("过拟合降级提示", "OOS_DEGRADED" in codes and over["gap"] == -0.8, str(over))
    over2 = opt.overfit_check({"sharpe": 1.0}, {"sharpe": -0.1},
                              {"metric": "sharpe", "direction": "max"})
    check("样本外无优势提示", "OOS_NO_EDGE" in {w["code"] for w in over2["warnings"]}, str(over2))

    top = opt.select_top([{"index": 0, "status": "ok", "score": 1.0},
                          {"index": 1, "status": "rejected", "score": None},
                          {"index": 2, "status": "ok", "score": 2.0}], 1)
    check("Top K 只取有效试次", len(top) == 1 and top[0]["index"] == 2, str(top))


def test_jobs():
    svc = _svc()
    r = svc.run_optimization(
        "t1", "1d", script="strategy/ma_cross",
        space={"fast": [5, 10, 15], "slow": [20, 30]}, method="grid",
        objective={"metric": "sharpe"}, constraints={"min_trades": 1},
        budget={"max_runs": 6, "max_seconds": 120}, holdout={"ratio": 0.3, "top_k": 2},
        seed=1, limit=300)
    check("寻优启动", r.get("status") == "ok" and r.get("total") == 6, str(r)[:200])
    st = _wait(svc, r["job_id"])
    check("网格寻优跑完", st.get("status") == "done" and st.get("done") == 6, str(st)[:200])
    check("选出 Top K 且样本外", len(st.get("top") or []) == 2
          and all(t.get("oos_stats") for t in st["top"]), str(st.get("top"))[:200])
    check("只登记 Top K 结果", len(st.get("registered_result_ids") or []) == 2
          and len(svc.list_results("t1")["results"]) == 2,
          f"registered={st.get('registered_result_ids')} board={len(svc.list_results('t1')['results'])}")
    rid = st["best"]["result_id"]
    summary = svc.get_result(rid, "summary")["result"]
    batch = summary.get("batch") or {}
    check("优化结果带 batch/phase", batch.get("kind") == "optimize"
          and batch.get("phase") == "oos" and batch.get("is_stats") and batch.get("oos_stats"),
          str(batch)[:200])
    check("样本外窗口不重叠",
          batch["oos_stats"].get("trade_count") is not None
          and st["best"]["is_stats"] is not batch["oos_stats"], str(batch)[:200])

    # 无样本外：登记 Top K 样本内
    svc2 = _svc()
    r2 = svc2.run_optimization(
        "t1", "1d", script="strategy/ma_cross",
        space={"fast": [5, 10], "slow": [20, 30]}, method="grid",
        budget={"max_runs": 4}, holdout={"ratio": 0, "top_k": 2}, seed=2, limit=300)
    st2 = _wait(svc2, r2["job_id"])
    check("无样本外也能选 Top K", st2.get("status") == "done"
          and len(st2.get("top") or []) == 2, str(st2)[:200])
    check("无样本外登记 + 警告", len(st2.get("registered_result_ids") or []) == 2
          and any(w["code"] == "NO_HOLDOUT" for w in st2.get("warnings") or []),
          str(st2.get("warnings")))
    check("无样本外结果 batch.phase=is",
          (svc2.get_result(st2["best"]["result_id"], "summary")["result"]
           .get("batch") or {}).get("phase") == "is")

    # 取消
    svc3 = _svc()
    r3 = svc3.run_optimization(
        "t1", "1d", script="strategy/ma_cross",
        space={"fast": [3, 5, 8, 10, 12, 15, 18, 20],
               "slow": [20, 25, 30, 35, 40, 50, 60, 80]},
        method="random", budget={"max_runs": 60, "max_seconds": 120},
        holdout={"ratio": 0.3, "top_k": 2}, seed=5, limit=300)
    svc3.cancel_optimization(r3["job_id"])
    st3 = _wait(svc3, r3["job_id"])
    check("取消寻优", st3.get("status") == "cancelled", str(st3)[:200])

    # 参数校验
    svc4 = _svc()
    cases = [
        ({"space": {}}, "SPACE_EMPTY"),
        ({"space": {"nope": [1]}}, "SPACE_INVALID"),
        ({"space": {"fast": [5]}, "method": "nope"}, "METHOD_INVALID"),
        ({"space": {"fast": [5]}, "budget": {"max_runs": 1}}, "BUDGET_INVALID"),
        ({"space": {"fast": [5]}, "holdout": {"ratio": 0.9}}, "HOLDOUT_INVALID"),
        ({"space": {"fast": [5]}, "objective": {"metric": "nope"}}, "OBJECTIVE_INVALID"),
        ({"space": {"fast": [5]}, "constraints": {"max_drawdown": 2}}, "CONSTRAINT_INVALID"),
    ]
    for kw, code in cases:
        out = svc4.run_optimization("t1", "1d", script="strategy/ma_cross",
                                    limit=300, **kw)
        check(f"校验 {code}", code in str(out.get("error")), str(out))


def test_store_migration_and_hash():
    tmp = Path(tempfile.mkdtemp(prefix="ak_opt_test_"))
    try:
        db = tmp / "v2.db"
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA user_version=2")
        conn.execute("""CREATE TABLE presets (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL DEFAULT '', script TEXT NOT NULL,
            name TEXT NOT NULL, params TEXT NOT NULL, note TEXT, origin TEXT,
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)""")
        conn.commit()
        conn.close()
        st = Store(db, app_version="0.6.5")
        cols = {r[1] for r in st._conn.execute("PRAGMA table_info(presets)").fetchall()}
        check("v2 → v3 迁移加 script_sha256", "script_sha256" in cols
              and st.stats()["schema"] == 3, str(cols))
        st.close()

        # 方案记录策略哈希 + 策略变更提示
        scripts = tmp / "scripts"
        (scripts / "strategy").mkdir(parents=True)
        shutil.copy(ROOT / "agentkline" / "resources" / "scripts" / "strategy" / "ma_cross.py",
                    scripts / "strategy" / "ma_cross.py")
        svc = AgentKlineService(str(scripts), data_dir=str(tmp / "data"))
        svc.create_board("h1", None, None, "BT/USDT", "datasource/mock_btc", {"days": 120})
        saved = svc.save_preset("h1", "hash-test", script="strategy/ma_cross")
        check("方案保存带哈希", saved.get("status") == "ok"
              and len(saved["preset"].get("script_sha256") or "") == 64, str(saved)[:160])
        rows = svc.list_presets("h1")["presets"]
        check("策略未变不告警", rows and rows[0]["script_changed"] is False, str(rows)[:160])
        with open(scripts / "strategy" / "ma_cross.py", "a", encoding="utf-8") as f:
            f.write("\n# changed\n")
        rows2 = svc.list_presets("h1")["presets"]
        check("策略变更 → script_changed", rows2 and rows2[0]["script_changed"] is True,
              str(rows2)[:160])
        svc.store.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("== 纯函数 ==")
    test_pure()
    print("== 作业 ==")
    test_jobs()
    print("== 现场库/哈希 ==")
    test_store_migration_and_hash()
    print(f"\nOptimizer: {ok} passed, {len(bad)} failed")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
