#!/usr/bin/env python3
"""结果层口径/校验单测（0.6.0）。无 pytest 依赖：python tools/test_results_unit.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkline.core import results as R

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


def main():
    # 口径：100k → 110k → 105k → 120k；HWM 从初始资金起，最大回撤 -4.545%
    times = [1_700_000_000_000 + i * 86_400_000 for i in range(4)]
    vals = [100_000, 110_000, 105_000, 120_000]
    trades = [{"entry_time": times[0], "exit_time": times[1], "pnl": 1000, "fee": 10, "holding_bars": 3},
              {"entry_time": times[1], "exit_time": times[2], "pnl": -500, "fee": 5, "holding_bars": 2},
              {"entry_time": times[2], "exit_time": times[3], "pnl": -300, "fee": 5, "holding_bars": 4}]
    s = R.compute_stats_full(times, vals, trades, 100_000, 365)
    check("总收益 20%", abs(s["total_return"] - 0.2) < 1e-9, s["total_return"])
    check("HWM 含初始资金 → 回撤 -4.545%", abs(s["max_drawdown"] + 0.04545454545) < 1e-8, s["max_drawdown"])
    check("胜率 1/3", abs(s["win_rate"] - 1 / 3) < 1e-9)
    check("盈亏比 2.5", abs(s["profit_loss_ratio"] - 2.5) < 1e-9, s["profit_loss_ratio"])
    check("利润因子 1.25", abs(s["profit_factor"] - 1.25) < 1e-9, s["profit_factor"])
    check("最大连败 2", s["max_consecutive_loss"] == 2)
    check("平均持仓 3", abs(s["avg_holding_bars"] - 3) < 1e-9)
    check("期末权益 120k", s["final_value"] == 120_000)

    # 无亏损：两个比值给 None，不冒充 0
    s2 = R.compute_stats_full([times[0], times[1]], [1000, 1100], [{"pnl": 5, "fee": 0}], 1000, 365)
    check("无亏损 PF=None", s2["profit_factor"] is None)
    check("无亏损 盈亏比=None", s2["profit_loss_ratio"] is None)

    # 校验：equity[0] 必须等于初始资金
    good = {"equity": {"times": times, "values": vals}, "run": {"initial_cash": 100_000},
            "strategy": {"id": "strategy/x"}}
    out = R.normalize_result(good, "b", "1d", bars=[])
    check("合法导入", "result" in out and out["result"]["status"] == "no_signals", str(out)[:120])
    u = R.normalize_result(dict(good, units={"quantity": "BTC", "currency": "USDT"}), "b", "1d", bars=[])
    check("units 原样保留", u["result"]["units"] == {"quantity": "BTC", "currency": "USDT"},
          str(u["result"].get("units")))
    u2 = R.normalize_result(good, "b", "1d", bars=[])
    check("units 缺省为空", u2["result"]["units"] == {"quantity": "", "currency": ""},
          str(u2["result"].get("units")))
    bad1 = dict(good, equity={"times": times, "values": [v + 1 for v in vals]})
    check("equity[0]!=初始资金 拒收", "error" in R.normalize_result(bad1, "b", "1d", bars=[]))
    bad2 = dict(good, equity={"times": [times[1], times[0]] + times[2:], "values": vals})
    check("时间轴非递增 拒收", "error" in R.normalize_result(bad2, "b", "1d", bars=[]))
    check("空 equity 拒收", "error" in R.normalize_result({"equity": {"times": [], "values": []}}, "b", "1d", bars=[]))

    # 状态推断
    r = R.normalize_result({"equity": {"times": times, "values": vals}, "run": {"initial_cash": 100_000}}, "b", "1d", bars=[])
    check("无成交 → no_signals", r["result"]["status"] == "no_signals")
    r2 = R.normalize_result({"equity": {"times": times, "values": vals}, "run": {"initial_cash": 100_000},
                             "fills": [{"time": times[0], "signed_qty": 1}]}, "b", "1d", bars=[])
    check("有成交无平仓 → open_position_only", r2["result"]["status"] == "open_position_only")

    # 数据质量：重复时间戳 + 缺口
    bars = [{"timestamp": t, "high": 2, "low": 1} for t in (1000, 2000, 3000, 9000)]
    q = R.data_quality(bars)
    check("缺口被标记", q["gaps"] >= 1 and q["verdict"] == "warn", str(q))
    q2 = R.data_quality([{"timestamp": 1000, "high": 2, "low": 1},
                         {"timestamp": 1000, "high": 2, "low": 1}])
    check("重复时间戳 → bad", q2["verdict"] == "bad" and q2["duplicates"] == 1, str(q2))

    # id 自增
    check("id 自增", R.next_result_id({"bt_x_1": 1, "bt_x_2": 2}, "strategy/x") == "bt_x_3")

    print(f"\nResults: {ok} passed, {len(bad)} failed")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
