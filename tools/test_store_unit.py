#!/usr/bin/env python3
"""现场库单测（0.6.3）：落盘/恢复/懒加载/自动淘汰/损坏旁路。无 pytest 依赖：
    python tools/test_store_unit.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkline.core.store import Store, SCHEMA_VERSION
from agentkline.core.state import StateManager
from agentkline.core.results import MAX_RESULTS_PER_BOARD, summarize

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


def _inst(inst_id="ma1"):
    return {"inst_id": inst_id, "kind": "recipe", "script": "indicator/ma",
            "params": {"n": 5}, "scope": "board", "tf": None, "target": None,
            "style": {"color": "#fff"}, "lines_style": None, "visible": True,
            "display_name": None, "custom_label": False, "auto_label": "MA(5)", "blob": None}


def _result(rid, created, board="b1", tf="1d", points=3):
    times = [1_700_000_000_000 + i * 60_000 for i in range(points)]
    values = [100.0 + i for i in range(points)]
    return {"result_id": rid, "display_name": rid, "created_at": created,
            "status": "no_signals", "data": {"board": board, "timeframe": tf},
            "stats": {"total_return": 0.01}, "strategy": {"id": "strategy/x"},
            "equity": {"times": times, "values": values},
            "trades": [{"pnl": 1.5, "entry_time": times[0], "exit_time": times[-1]}],
            "fills": [{"time": times[0], "signed_qty": 1}],
            "benchmark": {"id": "buy_hold", "times": times, "values": values}}


def main():
    tmp = Path(tempfile.mkdtemp(prefix="ak_store_"))
    try:
        db = tmp / "state.db"
        store = Store(db, app_version="0.6.2")
        check("建库 schema 版本", store.stats()["schema"] == SCHEMA_VERSION)

        sm = StateManager()
        sm.restore(store)
        sm.create_board("b1", "板一", ["1d", "1h"])
        sm.create_timeframe("b1", "4h")
        sm.add_instance("b1", _inst())
        sm.add_drawing("b1", {"type": "hline", "price": 100}, "1d")
        sm.create_subplot("b1", "1d", "macd", 150, "MACD")
        res = _result("bt_x_1", 100)
        add = sm.add_result("b1", res)
        check("结果登记无淘汰", add.get("status") == "ok" and not add.get("evicted"), str(add))

        # 重启：新的 Store + StateManager 从同一文件恢复
        store2 = Store(db)
        sm2 = StateManager()
        sm2.restore(store2)
        b = sm2.get_board("b1")
        check("板恢复", b is not None and b.name == "板一")
        check("周期恢复", b.intervals == ["1h", "4h", "1d"], str(b.intervals))
        check("当前周期恢复", b.current_timeframe == "1d")
        check("指标实例恢复", list(b.ind_registry) == ["ma1"] and
              b.ind_registry["ma1"]["params"] == {"n": 5})
        check("画线恢复", len(b.drawings) == 1 and
              next(iter(b.drawings.values()))["type"] == "hline")
        check("副图恢复", [s["name"] for s in b.timeframes["1d"].subplots.values()] == ["macd"])
        check("结果摘要恢复", list(b.results) == ["bt_x_1"])
        check("摘要带计数", b.results["bt_x_1"]["equity_points"] == 3 and
              b.results["bt_x_1"]["trade_count"] == 1)
        check("摘要态无产物", "equity" not in b.results["bt_x_1"])
        check("last_board 恢复", sm2.current_board_id == "b1")

        full = sm2.hydrate_result("bt_x_1")
        check("懒加载补净值", full.get("equity", {}).get("values") == res["equity"]["values"])
        check("懒加载补交易", full.get("trades") == res["trades"])
        check("懒加载后内存替换", "equity" in sm2.get_result("bt_x_1"))
        check("list_results 计数不归零",
              sm2.list_results("b1")[0]["equity_points"] == 3, str(sm2.list_results("b1")[0]))

        # 改名落盘
        sm2.rename_result("bt_x_1", "新名字")
        store3 = Store(db)
        sm3 = StateManager()
        sm3.restore(store3)
        check("改名持久", sm3.get_result("bt_x_1")["display_name"] == "新名字")

        # 自动淘汰：灌满上限再跑一条
        sm3.create_board("b2", "板二", ["1d"])
        for i in range(MAX_RESULTS_PER_BOARD):
            r = sm3.add_result("b2", _result(f"bt_y_{i}", 1000 + i, board="b2"))
            if r.get("error"):
                check("灌满上限", False, r["error"])
                break
        check("灌满到上限", len(sm3.get_board("b2").results) == MAX_RESULTS_PER_BOARD)
        oldest_id = min(sm3.get_board("b2").results,
                        key=lambda k: sm3.get_board("b2").results[k]["created_at"])
        add2 = sm3.add_result("b2", _result("bt_y_new", 99_999, board="b2"))
        check("超限自动淘汰 1 条", len(add2.get("evicted") or []) == 1, str(add2))
        check("淘汰的是最旧", add2["evicted"][0]["result_id"] == oldest_id)
        check("内存保持上限", len(sm3.get_board("b2").results) == MAX_RESULTS_PER_BOARD)
        check("磁盘保持上限",
              len(store3.load_result_summaries("b2")) == MAX_RESULTS_PER_BOARD,
              str(len(store3.load_result_summaries("b2"))))
        check("淘汰行已删净", store3.load_result(oldest_id) is None)
        check("事件留痕", any(e["kind"] == "result_evict" for e in store3.recent_events(100)))

        # 删板级联
        before = store3.count_results()
        sm3.delete_board("b2")
        check("删板级联删结果", store3.count_results() == before - MAX_RESULTS_PER_BOARD)
        check("删板后板数", store3.count_boards() == 1)

        # 雷达
        store3.save_watchlist([{"id": "default", "name": "默认",
                                "rows": [{"source": "datasource/mock_btc", "symbol": "BTC/USDT"}]},
                               {"id": "grp_a", "name": "A", "rows": []}])
        wl = Store(db).load_watchlist()
        check("雷达恢复", [g["id"] for g in wl] == ["default", "grp_a"] and
              wl[0]["rows"][0]["symbol"] == "BTC/USDT")

        store3.close()
        store2.close()
        store.close()

        # 损坏旁路：写垃圾再开
        (tmp / "bad.db").write_bytes(b"this is not a sqlite database" * 100)
        bad_store = Store(tmp / "bad.db")
        check("坏库旁路后可用", bad_store.stats()["schema"] == SCHEMA_VERSION)
        quarantined = list(tmp.glob("bad.db.corrupt-*"))
        check("坏库改名保留", len(quarantined) == 1, str(quarantined))
        bad_store.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nStore: {ok} passed, {len(bad)} failed")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
