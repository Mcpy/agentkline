#!/usr/bin/env python3
"""0.7.2 模拟盘 soak 记录器（默认 72h，不创建/停止会话）。

用法：
  .venv/bin/python tools/paper_soak.py --hours 72 --interval 60 \
      --base http://127.0.0.1:8765 --out /tmp/ak_paper_soak.jsonl

每轮记录：会话状态/游标/数据年龄/窗口 actual，Hub 的 upstream/cache/inflight/
429/退避/延迟；每 24h 对 running 会话跑 paper_audit，可选 reconcile。
只读观测；reconcile 会写一条对账事件（与面板按钮同口径）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _request(url: str, *, token: str = None, method: str = "GET",
             payload: dict = None, timeout: float = 30.0):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _compact_runtime(rt: dict) -> dict:
    hub = rt.get("marketdata") or {}
    return {
        "version": rt.get("version"),
        "paper": rt.get("paper") or {},
        "sessions": rt.get("sessions") or [],
        "hub": {k: hub.get(k) for k in (
            "requests", "upstream", "cache_hits", "inflight_hits", "errors",
            "rate_limited", "backoff_skips", "budget_timeouts", "cache_entries",
            "inflight", "avg_latency_ms", "max_latency_ms")},
    }


def _audit(base: str, sid: str) -> dict:
    cmd = [sys.executable, str(ROOT / "tools/paper_audit.py"),
           "--session-id", sid, "--base", base]
    cp = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                        timeout=180)
    return {"session_id": sid, "returncode": cp.returncode,
            "tail": (cp.stdout or cp.stderr or "").strip().splitlines()[-3:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--token", default=os.environ.get("AGENTKLINE_TOKEN") or "")
    ap.add_argument("--hours", type=float, default=72.0)
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--audit-every", type=float, default=24 * 3600.0,
                    help="秒；0=不做审计")
    ap.add_argument("--reconcile", action="store_true",
                    help="每日审计后额外跑一次 paper vs backtest 对账")
    ap.add_argument("--out", default="/tmp/ak_paper_soak.jsonl")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    token = args.token or None
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    end = start + max(0.001, args.hours) * 3600.0
    next_audit = start + args.audit_every if args.audit_every > 0 else None
    loops = errors = 0
    print(f"soak start base={base} hours={args.hours} interval={args.interval}s "
          f"out={out}", flush=True)
    with out.open("a", encoding="utf-8") as fh:
        while time.time() < end:
            loops += 1
            row = {"ts": int(time.time() * 1000), "elapsed_s": round(time.time() - start, 1)}
            try:
                rt = _request(f"{base}/api/paper/runtime", token=token, timeout=30)
                row.update(_compact_runtime(rt))
                for sid in [s.get("session_id") for s in row["sessions"]
                            if s.get("status") == "running"]:
                    if next_audit is not None and time.time() >= next_audit:
                        row.setdefault("audits", []).append(_audit(base, sid))
                        if args.reconcile:
                            try:
                                rec = _request(
                                    f"{base}/api/paper/sessions/{sid}/reconcile",
                                    token=token, method="POST", payload={},
                                    timeout=180)
                                row.setdefault("reconcile", []).append({
                                    "session_id": sid, "verdict": rec.get("verdict"),
                                    "diff_counts": rec.get("diff_counts")})
                            except Exception as exc:  # noqa: BLE001
                                row.setdefault("reconcile", []).append({
                                    "session_id": sid, "error": str(exc)})
                if next_audit is not None and time.time() >= next_audit:
                    next_audit += args.audit_every
            except Exception as exc:  # noqa: BLE001 - soak 不能因一次超时退出
                errors += 1
                row["error"] = f"{type(exc).__name__}: {exc}"
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            fh.flush()
            if loops % 60 == 0:
                print(f"soak alive loops={loops} errors={errors} "
                      f"elapsed={row['elapsed_s']}s", flush=True)
            time.sleep(max(1.0, min(args.interval, end - time.time())))

    summary = {"hours": args.hours, "loops": loops, "errors": errors,
               "out": str(out), "finished_at": int(time.time() * 1000)}
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
