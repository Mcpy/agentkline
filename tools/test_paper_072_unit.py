#!/usr/bin/env python3
"""0.7.2 模拟盘恢复/故障/多会话单测。

覆盖：重复 bar、缺口事件、修订事件、运行中重启自动恢复、10 会话独立账本。
无 pytest 依赖：.venv/bin/python tools/test_paper_072_unit.py
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkline.core.service import AgentKlineService

ok = 0
bad = []
DAY = 86_400_000


def check(name, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        bad.append(name)
        print(f"  ❌ {name} {detail}")


def make_bars(n=80, start=100.0):
    base = int(time.time() * 1000) - (n + 10) * DAY
    out, px = [], start
    for i in range(n):
        px += 0.5
        out.append({"timestamp": base + i * DAY, "open": px,
                    "high": px + 1, "low": px - 1, "close": px + 0.2,
                    "volume": 1000})
    return base, out


def new_bar(base, i, px):
    return {"timestamp": base + i * DAY, "open": px + 1.0,
            "high": px + 2.0, "low": px - 1.0, "close": px + 1.3,
            "volume": 1000}


def wait_bars(svc, sid, n, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        s = svc.paper.get(sid)
        if s.get("bars_processed", 0) >= n:
            return s
        time.sleep(0.05)
    return svc.paper.get(sid)


def events(svc, sid, limit=200):
    page = svc.paper.events(sid, 0, limit)
    return page.get("items") or []


def main():
    tmp = Path(tempfile.mkdtemp(prefix="ak_paper072_"))
    try:
        svc = AgentKlineService(str(Path("scripts")), {}, data_dir=str(tmp))
        base, bars = make_bars()
        svc.state.create_board("pg", name="Gap", intervals=["1d"])
        svc.state.set_ohlcv("pg", "1d", bars)
        sid = svc.paper.create("pg", "1d", "strategy/ma_cross")["session_id"]
        svc.paper.start(sid)
        b1 = new_bar(base, len(bars), bars[-1]["close"])
        allbars = bars + [b1]
        svc.state.set_ohlcv("pg", "1d", allbars)
        svc.paper.on_bars("pg", "1d", bars, allbars)
        s = wait_bars(svc, sid, 1)
        check("首根新 bar 处理一次", s.get("bars_processed") == 1, str(s.get("bars_processed")))

        # 重复轮询
        svc.paper.on_bars("pg", "1d", allbars, allbars)
        time.sleep(0.25)
        check("重复轮询不重复处理", svc.paper.get(sid).get("bars_processed") == 1)

        # 已处理 P 被修订：只写 PAPER_BAR_REVISED，不推进 bars_processed
        p_idx = len(allbars) - 2
        old_close = allbars[p_idx]["close"]
        allbars[p_idx] = {**allbars[p_idx], "close": old_close + 2.0}
        svc.state.set_ohlcv("pg", "1d", allbars)
        svc.paper._process(sid)
        time.sleep(0.3)
        rev = [e for e in events(svc, sid) if e["payload"].get("code") == "PAPER_BAR_REVISED"]
        check("修订 bar 写 PAPER_BAR_REVISED", len(rev) == 1, str(rev[:1]))
        check("修订不推进账本", svc.paper.get(sid).get("bars_processed") == 1)

        # 缺口：跳过 2 根
        b2 = new_bar(base, len(allbars) + 2, allbars[-1]["close"])
        allbars.append(b2)
        svc.state.set_ohlcv("pg", "1d", allbars)
        svc.paper.on_bars("pg", "1d", allbars[:-1], allbars)
        s = wait_bars(svc, sid, 2)
        gap = [e for e in events(svc, sid) if e["payload"].get("code") == "PAPER_BAR_GAP"]
        check("缺口继续处理", s.get("bars_processed") == 2, str(s.get("bars_processed")))
        check("缺口写 PAPER_BAR_GAP 且 missing=2",
              len(gap) == 1 and gap[0]["payload"].get("missing_bars") == 2, str(gap[:1]))

        # 回填旧 bar：只更新历史，不重放、不推进游标
        old = {"timestamp": base - DAY, "open": 90.0, "high": 91.0,
               "low": 89.0, "close": 90.5, "volume": 1000}
        allbars = [old] + allbars
        svc.state.set_ohlcv("pg", "1d", allbars)
        svc.paper.on_bars("pg", "1d", allbars[1:], allbars)
        time.sleep(0.25)
        check("回填旧 bar 不重放", svc.paper.get(sid).get("bars_processed") == 2,
              str(svc.paper.get(sid).get("bars_processed")))

        # 模拟数据源短历史替换：之前 1200 根，现在只剩 82 根
        svc.paper._get(sid)["state"]["window_actual"] = 1200
        svc.paper._process(sid)
        time.sleep(0.2)
        wc = [e for e in events(svc, sid)
              if e["payload"].get("code") == "PAPER_WINDOW_ACTUAL_CHANGED"]
        check("短历史替换写 PAPER_WINDOW_ACTUAL_CHANGED", len(wc) == 1,
              str(wc[:1]))

        rt = svc.paper.runtime()
        check("runtime 返回 Hub 指标", isinstance(rt.get("marketdata"), dict)
              and "cache_hits" in rt["marketdata"], str(rt)[:300])
        check("runtime 返回会话状态", len(rt.get("sessions") or []) == 1
              and rt["sessions"][0]["status"] == "running", str(rt.get("sessions")))

        # 运行中重启：same DB，新的 service，自动拉起且不重复
        svc.store.close()
        del svc
        svc2 = AgentKlineService(str(Path("scripts")), {}, data_dir=str(tmp))
        svc2.state.set_ohlcv("pg", "1d", allbars)
        s2 = svc2.paper.get(sid)
        check("重启用 running 自动恢复", s2.get("status") == "running", str(s2.get("status")))
        restart = [e for e in events(svc2, sid)
                   if e["payload"].get("code") == "PAPER_RESUMED_AFTER_RESTART"]
        check("写 PAPER_RESUMED_AFTER_RESTART", len(restart) == 1, str(restart[:1]))
        svc2.paper.on_bars("pg", "1d", allbars, allbars)
        time.sleep(0.3)
        check("重启后不重复处理", svc2.paper.get(sid).get("bars_processed") == 2,
              str(svc2.paper.get(sid).get("bars_processed")))
        # 数据过期：超过 2 个周期没有新 bar，数据源报错时写 PAPER_DATA_STALE
        svc2.state.create_board("pstale", name="Stale", intervals=["1d"])
        _, stalebars = make_bars(n=80)
        svc2.state.set_ohlcv("pstale", "1d", stalebars)
        pst = svc2.paper.create("pstale", "1d", "strategy/ma_cross")["session_id"]
        svc2.paper.start(pst)
        sess = svc2.paper._get(pst)
        sess["last_seen_ts"] = int(time.time() * 1000) - 10 * DAY
        svc2.paper.on_source_error("pstale", "1d", "boom")
        time.sleep(0.2)
        stale = [e for e in events(svc2, pst)
                 if e["payload"].get("code") == "PAPER_DATA_STALE"]
        check("数据过期写 PAPER_DATA_STALE", len(stale) == 1, str(stale[:1]))

        svc2.paper.stop_all()
        svc2.store.close()

        # 10 会话：各板独立账本，每板只处理一根，不串账
        tmp2 = Path(tempfile.mkdtemp(prefix="ak_paper072_scale_"))
        try:
            svc3 = AgentKlineService(str(Path("scripts")), {}, data_dir=str(tmp2))
            base3, bars3 = make_bars(n=60)
            sids = []
            for i in range(10):
                bid = f"scale{i}"
                svc3.state.create_board(bid, name=bid, intervals=["1d"])
                svc3.state.set_ohlcv(bid, "1d", bars3)
                out = svc3.paper.create(bid, "1d", "strategy/ma_cross")
                check(f"10 会话创建 {i}", bool(out.get("session_id")), str(out))
                sids.append(out["session_id"])
                svc3.paper.start(out["session_id"])
            all3 = []
            for i, bid in enumerate(f"scale{i}" for i in range(10)):
                nb = new_bar(base3, len(bars3), bars3[-1]["close"])
                all3.append((bid, nb))
                svc3.state.set_ohlcv(bid, "1d", bars3 + [nb])
                svc3.paper.on_bars(bid, "1d", bars3, bars3 + [nb])
            end = time.time() + 8
            while time.time() < end:
                done = sum(svc3.paper.get(x).get("bars_processed", 0) >= 1 for x in sids)
                if done == 10:
                    break
                time.sleep(0.1)
            got = [svc3.paper.get(x).get("bars_processed") for x in sids]
            check("10 会话各自处理 1 根", got == [1] * 10, str(got))
            check("10 会话独立无串账", len({svc3.paper.get(x).get("session_id") for x in sids}) == 10)
            rt3 = svc3.paper.runtime()
            check("runtime 聚合 10 会话", len(rt3.get("sessions") or []) == 10,
                  str(len(rt3.get("sessions") or [])))
            svc3.paper.stop_all()
            svc3.store.close()
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nPaper 0.7.2: {ok} passed, {len(bad)} failed")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
