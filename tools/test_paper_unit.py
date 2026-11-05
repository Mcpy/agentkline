#!/usr/bin/env python3
"""模拟盘单测（0.7.0）：schema v5 / 会话 / 游标去重 / 暂停跳过 / 缺口门禁 / 停止物化。

无 pytest 依赖：python tools/test_paper_unit.py
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkline.core.service import AgentKlineService
from agentkline.core.store import SCHEMA_VERSION
from agentkline.core.paper import _is_closed

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


def make_bars(n=120, base=None, start=100.0):
    base = base or (int(time.time() * 1000) - (n + 10) * 86_400_000)
    out = []
    px = start
    for i in range(n):
        px += 0.5
        out.append({"timestamp": base + i * 86_400_000, "open": px,
                    "high": px + 1, "low": px - 1, "close": px + 0.2,
                    "volume": 1000})
    return base, out


def wait_bars(svc, sid, n, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        s = svc.paper.get(sid)
        if s.get("bars_processed", 0) >= n:
            return s
        time.sleep(0.05)
    return svc.paper.get(sid)


def new_bar(base, i, px):
    return {"timestamp": base + i * 86_400_000, "open": px + 1.0,
            "high": px + 2.0, "low": px - 1.0, "close": px + 1.3,
            "volume": 1000}


def main():
    tmp = Path(tempfile.mkdtemp(prefix="ak_paper_"))
    try:
        svc = AgentKlineService(str(Path("scripts")), {}, data_dir=str(tmp))
        now = 1_800_000_000_000
        bar = {"timestamp": now - 15 * 60_000}
        check("settle 未到不处理", not _is_closed(bar, "15m", now, 15_000))
        check("settle 到后才处理", _is_closed(bar, "15m", now + 15_000, 15_000))
        check("schema v5", SCHEMA_VERSION == 5 and svc.store.stats()["schema"] == 5)
        tables = {r[0] for r in svc.store._rows(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        check("paper 三表建齐",
              {"paper_sessions", "paper_events", "paper_equity"} <= tables)

        svc.state.create_board("p1", name="P1", intervals=["1d"])
        base, bars = make_bars()
        svc.state.set_ohlcv("p1", "1d", bars)
        out = svc.paper.create("p1", "1d", "strategy/ma_cross")
        check("创建会话", out.get("status") == "created" and out.get("session_id"), str(out))
        sid = out["session_id"]
        check("创建即冻结参数", out.get("params", {}).get("fast") == 10, str(out.get("params")))
        dup = svc.paper.create("p1", "1d", "strategy/ma_cross")
        check("同板同周期只允许一个", dup.get("code") == "PAPER_SESSION_EXISTS", str(dup))

        started = svc.paper.start(sid)
        check("启动", started.get("status") == "running")
        time.sleep(0.2)
        check("启动不回溯历史", svc.paper.get(sid).get("bars_processed") == 0)
        check("运行中禁止删除", svc.paper.delete(sid).get("code") == "PAPER_RUNNING")

        # 新 bar B：P 的 target 在 B 开盘成交
        b1 = new_bar(base, len(bars), bars[-1]["close"])
        allbars = bars + [b1]
        svc.state.set_ohlcv("p1", "1d", allbars)
        svc.paper.on_bars("p1", "1d", bars, allbars)
        s = wait_bars(svc, sid, 1)
        check("新 bar 处理一次", s.get("bars_processed") == 1, str(s.get("bars_processed")))
        check("决策游标=P", s.get("cursor_ts") == bars[-1]["timestamp"],
              f"{s.get('cursor_ts')} vs {bars[-1]['timestamp']}")
        check("last_seen=B", s.get("last_seen_ts") == b1["timestamp"])
        ev = svc.paper.get(sid, include_events=True).get("events") or []
        kinds = [e["kind"] for e in ev]
        check("事件 decision/fill/equity", all(k in kinds for k in ("decision", "fill", "equity")),
              str(kinds))
        fill = next((e for e in ev if e["kind"] == "fill"), None)
        want = b1["open"] * (1 + 5 / 10_000.0)
        check("next-open 成交（含滑点）",
              fill and abs(fill["payload"]["price"] - want) < 1e-8,
              f"{fill and fill['payload']['price']} vs {want}")
        check("权益点入账", svc.paper.equity(sid).get("total") == 1)
        internal = svc.paper._get(sid)["state"]
        check("fill 带 bar index",
              all(int(f.get("index", -1)) >= 0 for f in internal.get("fills") or []),
              str(internal.get("fills")))
        detail = svc.paper.get(sid)
        check("detail 带持仓/成交/浮动盈亏",
              "open_trade" in detail and "trades" in detail and "fills" in detail
              and "unrealized_pnl" in detail, str(detail.keys()))

        # 重复轮询不重复处理
        svc.paper.on_bars("p1", "1d", allbars, allbars)
        time.sleep(0.25)
        check("重复 bar 不重复处理", svc.paper.get(sid).get("bars_processed") == 1)

        # 暂停：暂停期 bar 不处理；恢复默认跳过
        svc.paper.pause(sid)
        b2 = new_bar(base, len(allbars), b1["close"])
        b3 = new_bar(base, len(allbars) + 1, b2["close"])
        allbars += [b2, b3]
        svc.state.set_ohlcv("p1", "1d", allbars)
        svc.paper.on_bars("p1", "1d", allbars[:-2], allbars)
        time.sleep(0.2)
        check("暂停期不处理", svc.paper.get(sid).get("bars_processed") == 1)
        svc.paper.resume(sid)
        s = svc.paper.get(sid)
        check("恢复跳过暂停期", s.get("bars_processed") == 1, str(s.get("bars_processed")))
        ev = svc.paper.get(sid, include_events=True).get("events") or []
        check("恢复写 PAPER_RESUME_SKIP",
              any(e["kind"] == "warning" and e["payload"].get("code") == "PAPER_RESUME_SKIP"
                  for e in ev), str([e["payload"].get("code") for e in ev]))

        # 一次补处理超过上限 → paused_gap
        svc.paper.max_catchup = 1
        b4 = new_bar(base, len(allbars), b3["close"])
        b5 = new_bar(base, len(allbars) + 1, b4["close"])
        allbars += [b4, b5]
        svc.state.set_ohlcv("p1", "1d", allbars)
        svc.paper.on_bars("p1", "1d", allbars[:-2], allbars)
        time.sleep(0.3)
        s = svc.paper.get(sid)
        check("超补处理上限转 paused_gap", s.get("status") == "paused_gap", str(s.get("status")))
        check("paused_gap 不推进", s.get("bars_processed") == 1)

        # 恢复后继续一笔，然后停止物化
        svc.paper.resume(sid)
        b6 = new_bar(base, len(allbars), b5["close"])
        allbars.append(b6)
        svc.state.set_ohlcv("p1", "1d", allbars)
        svc.paper.on_bars("p1", "1d", allbars[:-1], allbars)
        s = wait_bars(svc, sid, 2)
        check("恢复后继续处理", s.get("bars_processed") == 2, str(s.get("bars_processed")))
        stopped = svc.paper.stop(sid)
        check("停止", stopped.get("status") == "stopped")
        time.sleep(0.2)
        s = svc.paper.get(sid)
        check("停止物化 result_id", bool(s.get("result_id")), str(s.get("result_id")))
        res = svc.state.get_board("p1").results.get(s.get("result_id"))
        check("结果 kind=paper", res and res.get("kind") == "paper", str(res and res.get("kind")))
        check("结果 batch 带 session",
              res and res.get("batch", {}).get("session_id") == sid,
              str(res and res.get("batch")))
        trades = svc.paper.get(sid).get("trades") or []
        bars_now = svc.state.get_ohlcv("p1", "1d")
        idx_by_ts = {int(b["timestamp"]): i for i, b in enumerate(bars_now)}
        check("回合 holding_bars 按时间戳重算",
              all(int(t.get("holding_bars") or -1) ==
                  max(0, idx_by_ts[int(t["exit_time"])] - idx_by_ts[int(t["entry_time"])])
                  for t in trades if t.get("entry_time") != t.get("exit_time")),
              str(trades))
        check("停止后不能重启", svc.paper.start(sid).get("code") == "PAPER_STOPPED")

        # 未启动的会话可直接删；删除后账本/会话都不可见
        svc.state.create_board("p2", name="P2", intervals=["1d"])
        svc.state.set_ohlcv("p2", "1d", allbars)
        p2sid = svc.paper.create("p2", "1d", "strategy/ma_cross")["session_id"]
        d = svc.paper.delete(p2sid)
        check("created 会话可删除", d.get("status") == "deleted"
              and svc.paper.get(p2sid).get("code") == "PAPER_NOT_FOUND", str(d))

        # 重启去重：同一现场库再起一个 service
        svc.store.close()
        del svc
        svc2 = AgentKlineService(str(Path("scripts")), {}, data_dir=str(tmp))
        svc2.state.set_ohlcv("p1", "1d", allbars)
        svc2.paper.on_bars("p1", "1d", allbars, allbars)
        time.sleep(0.3)
        s2 = svc2.paper.get(sid)
        check("重启后已停止会话不被拉起", s2.get("status") == "stopped")
        check("重启后不重复处理", s2.get("bars_processed") == 2, str(s2.get("bars_processed")))
        rid = s2.get("result_id")
        d = svc2.paper.delete(sid)
        check("停止后删除会话", d.get("status") == "deleted", str(d))
        check("删除会话默认保留 paper 结果",
              bool(rid) and rid in svc2.state.get_board("p1").results, str(rid))
        svc2.store.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nPaper: {ok} passed, {len(bad)} failed")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
