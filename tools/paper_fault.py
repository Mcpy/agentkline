#!/usr/bin/env python3
"""0.7.2 崩溃注入：在 bar 处理的关键点 SIGKILL，重启后检查不重复/不丢游标。

用法：.venv/bin/python tools/paper_fault.py
每个故障点用独立临时现场库，子进程在 hook 点被 SIGKILL，父进程重启并校验。
"""
from __future__ import annotations

import shutil
import signal
import subprocess
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


CHILD = r'''
import os, signal, sys, time
from pathlib import Path
root, tmp, point = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root)
from agentkline.core.service import AgentKlineService
DAY = 86_400_000
n = 80
base = int(time.time() * 1000) - (n + 10) * DAY
bars, px = [], 100.0
for i in range(n):
    px += 0.5
    bars.append({"timestamp": base + i * DAY, "open": px, "high": px + 1,
                 "low": px - 1, "close": px + 0.2, "volume": 1000})
svc = AgentKlineService(str(Path(root) / "scripts"), {}, data_dir=tmp)
svc.state.create_board("fault", name="fault", intervals=["1d"])
svc.state.set_ohlcv("fault", "1d", bars)
sid = svc.paper.create("fault", "1d", "strategy/ma_cross")["session_id"]
svc.paper.start(sid)
b1 = {"timestamp": base + n * DAY, "open": bars[-1]["close"] + 1,
      "high": bars[-1]["close"] + 2, "low": bars[-1]["close"] - 1,
      "close": bars[-1]["close"] + 1.3, "volume": 1000}
svc.state.set_ohlcv("fault", "1d", bars + [b1])
def hook(p, **kw):
    if p == point:
        os.kill(os.getpid(), signal.SIGKILL)
svc.paper.fault_hook = hook
svc.paper._process(sid)
print("NOT_KILLED", point)
'''


def wait_bars(svc, sid, n, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        s = svc.paper.get(sid)
        if s.get("bars_processed", 0) >= n:
            return s
        time.sleep(0.05)
    return svc.paper.get(sid)


def run_point(point: str):
    tmp = Path(tempfile.mkdtemp(prefix=f"ak_fault_{point}_"))
    try:
        cp = subprocess.run([sys.executable, "-c", CHILD, str(ROOT), str(tmp), point],
                            cwd=str(ROOT), capture_output=True, text=True, timeout=40)
        check(f"{point}: 子进程被 SIGKILL", cp.returncode == -signal.SIGKILL,
              f"rc={cp.returncode} out={cp.stdout[-200:]} err={cp.stderr[-300:]}")
        svc = AgentKlineService(str(ROOT / "scripts"), {}, data_dir=str(tmp))
        rows = svc.store.list_paper_sessions(limit=10)
        check(f"{point}: 重启后会话仍存在", len(rows) == 1, str(len(rows)))
        sid = rows[0]["session_id"]
        s = svc.paper.get(sid)
        check(f"{point}: 重启后自动 running", s.get("status") == "running",
              str(s.get("status")))
        before = s.get("bars_processed") or 0
        check(f"{point}: 崩溃点前的账本可解释",
              before == (1 if point == "after_persist" else 0), str(before))
        # 补喂同一根 B；after_persist 不应重复，before 点应补上且只一次
        bars = svc.state.get_ohlcv("fault", "1d")
        if not bars:
            # K 线不落盘，父进程重建同样的 81 根
            day = 86_400_000
            base = int(time.time() * 1000) - (80 + 10) * day
            bars, px = [], 100.0
            for i in range(80):
                px += 0.5
                bars.append({"timestamp": base + i * day, "open": px,
                             "high": px + 1, "low": px - 1, "close": px + 0.2,
                             "volume": 1000})
            bars.append({"timestamp": base + 80 * day, "open": bars[-1]["close"] + 1,
                         "high": bars[-1]["close"] + 2, "low": bars[-1]["close"] - 1,
                         "close": bars[-1]["close"] + 1.3, "volume": 1000})
            svc.state.set_ohlcv("fault", "1d", bars)
        svc.paper.on_bars("fault", "1d", bars, bars)
        s2 = wait_bars(svc, sid, 1)
        check(f"{point}: 恢复后只处理一次", s2.get("bars_processed") == 1,
              str(s2.get("bars_processed")))
        evs = svc.paper.events(sid, 0, 1000).get("items") or []
        decisions = [e for e in evs if e["kind"] == "decision"]
        equities = [e for e in evs if e["kind"] == "equity"]
        check(f"{point}: decision 不重复", len(decisions) == 1, str(len(decisions)))
        check(f"{point}: equity 不重复", len(equities) == 2, str(len(equities)))
        restart = [e for e in evs
                   if e["payload"].get("code") == "PAPER_RESUMED_AFTER_RESTART"]
        check(f"{point}: 写恢复事件", len(restart) == 1, str(len(restart)))
        svc.paper.stop_all()
        svc.store.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    for point in ("after_receive", "before_persist", "after_persist"):
        run_point(point)
    print(f"\nPaper fault: {ok} passed, {len(bad)} failed")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
