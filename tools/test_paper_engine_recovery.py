#!/usr/bin/env python3
"""0.7.3 paper engine retry / detail / auto-recovery / replay tests.

Run with: PYTHONPATH=. .venv/bin/python tools/test_paper_engine_recovery.py
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkline.core.service import AgentKlineService
from agentkline.backtest import runner as engine_runner
from agentkline.backtest.runner import EngineRunError

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


def make_bars(n=80):
    base = int(time.time() * 1000) - (n + 10) * DAY
    out, px = [], 100.0
    for i in range(n):
        px += 0.5
        out.append({"timestamp": base + i * DAY, "open": px, "high": px + 1,
                    "low": px - 1, "close": px + 0.2, "volume": 1000})
    return base, out


def bar(base, i, px):
    return {"timestamp": base + i * DAY, "open": px + 1, "high": px + 2,
            "low": px - 1, "close": px + 1.3, "volume": 1000}


def wait(svc, sid, pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        s = svc.paper.get(sid)
        if pred(s):
            return s
        time.sleep(0.05)
    return svc.paper.get(sid)


def setup(tmp, name):
    svc = AgentKlineService(str(Path("scripts")), {}, data_dir=str(tmp))
    svc.state.create_board(name, name=name, intervals=["1d"])
    base, bars = make_bars()
    svc.state.set_ohlcv(name, "1d", bars)
    sid = svc.paper.create(name, "1d", "strategy/ma_cross")["session_id"]
    svc.paper.start(sid)
    return svc, base, bars, sid


def main():
    orig = engine_runner.signal_spec
    tmp = Path(tempfile.mkdtemp(prefix="ak_paper_engine_"))
    try:
        # 1) transient retry then success
        svc, base, bars, sid = setup(tmp / "retry", "retry")
        calls = {"n": 0}
        def flaky(spec, timeout=60.0):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise EngineRunError("ENGINE_CRASH", "transient", stderr_tail="stderr: boom",
                                     exit_code=1)
            return {"target": 0.0, "reason": "test", "warnings": []}
        engine_runner.signal_spec = flaky
        b1 = bar(base, len(bars), bars[-1]["close"])
        allbars = bars + [b1]
        svc.state.set_ohlcv("retry", "1d", allbars)
        svc.paper.on_bars("retry", "1d", bars, allbars)
        s = wait(svc, sid, lambda x: x.get("bars_processed", 0) >= 1)
        check("引擎瞬时崩溃重试后继续", s.get("status") == "running"
              and s.get("bars_processed") == 1, str(s))
        evs = svc.paper.events(sid, 0, 1000).get("items") or []
        retries = [e for e in evs if (e.get("payload") or {}).get("code")
                   == "PAPER_ENGINE_RETRY"]
        check("写 PAPER_ENGINE_RETRY 事件", len(retries) == 2, str(len(retries)))
        svc.paper.stop_all(); svc.store.close()

        # 2) auto-recovery after one exhausted engine attempt
        svc, base, bars, sid = setup(tmp / "auto", "auto")
        svc.paper.engine_retries = 1
        svc.paper.auto_recovery_attempts = 1
        svc.paper.auto_recovery_delay_s = 0.1
        calls = {"n": 0}
        def fail_once(spec, timeout=60.0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise EngineRunError("ENGINE_CRASH", "once", stderr_tail="stderr: auto",
                                     exit_code=1)
            return {"target": 0.0, "reason": "test", "warnings": []}
        engine_runner.signal_spec = fail_once
        b1 = bar(base, len(bars), bars[-1]["close"])
        allbars = bars + [b1]
        svc.state.set_ohlcv("auto", "1d", allbars)
        svc.paper.on_bars("auto", "1d", bars, allbars)
        s = wait(svc, sid, lambda x: x.get("status") == "running"
                 and x.get("bars_processed", 0) >= 1, timeout=4.0)
        check("引擎错误后自动恢复", s.get("status") == "running"
              and s.get("bars_processed") == 1, str(s))
        evs = svc.paper.events(sid, 0, 1000).get("items") or []
        auto = [e for e in evs if (e.get("payload") or {}).get("code")
                == "PAPER_AUTO_RECOVERY"]
        check("写 PAPER_AUTO_RECOVERY 事件", len(auto) == 1, str(len(auto)))
        rows = svc.store.list_paper_sessions(limit=10)
        row = next((r for r in rows if r.get("session_id") == sid), {})
        check("自动恢复后 last_error 清空（内存 + 落盘）",
              s.get("last_error") is None and row.get("last_error") is None,
              f"mem={s.get('last_error')!r} db={row.get('last_error')!r}")
        svc.paper.stop_all(); svc.store.close()

        # 3) replay from last_seen after an error, no skip
        svc, base, bars, sid = setup(tmp / "replay", "replay")
        svc.paper.auto_recovery_attempts = 0
        calls = {"n": 0}
        def ok_engine(spec, timeout=60.0):
            calls["n"] += 1
            return {"target": 0.0, "reason": "test", "warnings": []}
        engine_runner.signal_spec = ok_engine
        b1 = bar(base, len(bars), bars[-1]["close"])
        allbars = bars + [b1]
        svc.state.set_ohlcv("replay", "1d", allbars)
        svc.paper.on_bars("replay", "1d", bars, allbars)
        wait(svc, sid, lambda x: x.get("bars_processed", 0) >= 1)
        b2 = bar(base, len(allbars), b1["close"])
        b3 = bar(base, len(allbars) + 1, b2["close"])
        allbars += [b2, b3]
        svc.state.set_ohlcv("replay", "1d", allbars)
        def fail_engine(spec, timeout=60.0):
            raise EngineRunError("ENGINE_CRASH", "persistent",
                                 stderr_tail="stderr: replay-detail", exit_code=1)
        engine_runner.signal_spec = fail_engine
        svc.paper.on_bars("replay", "1d", allbars[:-2], allbars)
        s = wait(svc, sid, lambda x: x.get("status") == "error", timeout=4.0)
        check("引擎连续失败转 error", s.get("status") == "error", str(s.get("status")))
        detail = svc.paper.get(sid).get("last_error_detail") or {}
        check("错误保留 stderr/detail", "replay-detail" in json.dumps(detail),
              str(detail))
        engine_runner.signal_spec = ok_engine
        out = svc.paper.resume(sid, mode="replay")
        check("replay 恢复接口", out.get("status") == "running", str(out)[:300])
        s = wait(svc, sid, lambda x: x.get("bars_processed", 0) >= 3, timeout=4.0)
        check("replay 重放缺失 bar", s.get("bars_processed") == 3,
              str(s.get("bars_processed")))
        evs = svc.paper.events(sid, 0, 1000).get("items") or []
        replay = [e for e in evs if (e.get("payload") or {}).get("code")
                  == "PAPER_RESUME_REPLAY"]
        check("写 PAPER_RESUME_REPLAY 事件", len(replay) == 1, str(len(replay)))
        svc.paper.stop_all(); svc.store.close()

        # 4) replay 批量追平：刚收盘不足 replay_min_age_ms 的最新 bar 必须推迟
        #    （D14 门禁：交易所收盘价定稿延迟，立即记账会用暂定价）
        name = "replay_boundary"
        svc = AgentKlineService(str(Path("scripts")), {}, data_dir=str(tmp / "rboundary"))
        svc.state.create_board(name, name=name, intervals=["1m"])
        t0 = int(time.time() * 1000)
        span = 60_000
        old = [{"timestamp": t0 - 320_000 - (39 - i) * span,
                "open": 100 + i, "high": 101 + i, "low": 99 + i,
                "close": 100.5 + i, "volume": 1000} for i in range(40)]
        svc.state.set_ohlcv(name, "1m", old)
        sid = svc.paper.create(name, "1m", "strategy/ma_cross")["session_id"]
        svc.paper.start(sid)
        svc.paper.pause(sid)
        time.sleep(0.2)
        check("replay_min_age_ms 默认 60s", svc.paper.replay_min_age_ms == 60_000,
              str(svc.paper.replay_min_age_ms))
        # 追加 3 根已定稿 + 1 根刚收盘 20s 的 bar（已过 settle，但未过 60s）
        gap = [{"timestamp": t0 - 260_000 + i * span,
                "open": 140 + i, "high": 141 + i, "low": 139 + i,
                "close": 140.5 + i, "volume": 1000} for i in range(3)]
        fresh = {"timestamp": t0 - 80_000, "open": 143, "high": 144,
                 "low": 142, "close": 143.5, "volume": 1000}
        allb = old + gap + [fresh]
        svc.state.set_ohlcv(name, "1m", allb)
        svc.paper._replay_guard.add(sid)   # 模拟 replay 恢复
        with svc.paper._lock:
            svc.paper._get(sid)["status"] = "running"
        svc.paper._process(sid, now_ms=t0)
        s = svc.paper.get(sid)
        evs = svc.paper.events(sid, 0, 10000).get("items") or []
        eq_ts = {e.get("bar_ts") for e in evs if e.get("kind") == "equity"}
        check("批量追平已处理较早的缺口 bar",
              s.get("last_seen_ts") == t0 - 140_000, str(s.get("last_seen_ts")))
        check("刚收盘 20s 的最新 bar 被推迟（未记权益）",
              (t0 - 80_000) not in eq_ts, f"eq_ts={sorted(eq_ts)[-3:]}")
        # 时钟推进到该 bar 收盘 90s 后：应被正常处理
        svc.paper._process(sid, now_ms=t0 + 70_000)
        s = svc.paper.get(sid)
        evs = svc.paper.events(sid, 0, 10000).get("items") or []
        eq_ts = {e.get("bar_ts") for e in evs if e.get("kind") == "equity"}
        check("推进时间后最新 bar 正常记账",
              s.get("last_seen_ts") == t0 - 80_000 and (t0 - 80_000) in eq_ts,
              str(s.get("last_seen_ts")))
        check("保护期结束后清除 replay guard", sid not in svc.paper._replay_guard)
        check("推迟的 bar 未产生缺口告警",
              not [e for e in evs if (e.get("payload") or {}).get("code") == "PAPER_BAR_GAP"],
              "unexpected PAPER_BAR_GAP")

        # 4b) 单根缺口同样受保护（len(new)==1 的 replay 边界）
        name2 = "replay_boundary2"
        svc.state.create_board(name2, name=name2, intervals=["1m"])
        old2 = [dict(b) for b in old]
        svc.state.set_ohlcv(name2, "1m", old2)
        sid2 = svc.paper.create(name2, "1m", "strategy/ma_cross")["session_id"]
        svc.paper.start(sid2)
        svc.paper.pause(sid2)
        time.sleep(0.2)
        fresh2 = {"timestamp": t0 - 80_000, "open": 143, "high": 144,
                  "low": 142, "close": 143.5, "volume": 1000}
        svc.state.set_ohlcv(name2, "1m", old2 + [fresh2])
        svc.paper._replay_guard.add(sid2)
        with svc.paper._lock:
            svc.paper._get(sid2)["status"] = "running"
        svc.paper._process(sid2, now_ms=t0)
        s2 = svc.paper.get(sid2)
        evs2 = svc.paper.events(sid2, 0, 10000).get("items") or []
        eq2 = {e.get("bar_ts") for e in evs2 if e.get("kind") == "equity"}
        check("单根缺口的最新 bar 也被推迟",
              s2.get("last_seen_ts") == t0 - 320_000 and (t0 - 80_000) not in eq2,
              f"last_seen={s2.get('last_seen_ts')}")
        svc.paper._process(sid2, now_ms=t0 + 70_000)
        s2 = svc.paper.get(sid2)
        evs2 = svc.paper.events(sid2, 0, 10000).get("items") or []
        eq2 = {e.get("bar_ts") for e in evs2 if e.get("kind") == "equity"}
        check("单根缺口推进后正常记账",
              s2.get("last_seen_ts") == t0 - 80_000 and (t0 - 80_000) in eq2,
              str(s2.get("last_seen_ts")))
        svc.paper.stop_all(); svc.store.close()
    finally:
        engine_runner.signal_spec = orig
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nPaper engine recovery: {ok} passed, {len(bad)} failed")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
