#!/usr/bin/env python3
"""为 0.7.2 72h soak 创建 2 个画板 × 5 周期 = 10 个模拟盘会话。

用法：
  .venv/bin/python tools/setup_soak_072.py --base http://127.0.0.1:8895 \
      --token <token> --out /tmp/soak_sessions.json

只走 HTTP，不导入 agentkline，避免启动第二个 service 污染现场库。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

TFS = ["1m", "5m", "15m", "1h", "4h"]
BOARDS = [
    ("soak_btc", "BTC/USDT:USDT"),
    ("soak_eth", "ETH/USDT:USDT"),
]


def req(base, path, token=None, method="GET", payload=None, timeout=30):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(base.rstrip("/") + path, data=data,
                               headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_health(base, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            req(base, "/api/config", timeout=3)
            return True
        except Exception:
            time.sleep(1)
    return False


def ensure_board(base, token, bid, symbol):
    try:
        out = req(base, "/api/board", token, "POST", {
            "id": bid, "name": f"soak · {symbol}",
            "symbol": symbol, "source": "datasource/binance",
            "intervals": TFS, "poll_s": 5,
        }, timeout=60)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        # 重复运行时复用现有板
        if exc.code in (400, 409):
            boards = req(base, "/api/boards", token)
            for b in boards.get("boards") or []:
                if b.get("id") == bid:
                    return bid
        raise RuntimeError(f"create board {bid} failed: {exc.code} {body[:300]}") from exc
    if out.get("error"):
        raise RuntimeError(f"create board {bid}: {out['error']}")
    return out.get("id") or bid


def wait_bars(base, token, bid, tf, timeout=90):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            out = req(base, f"/api/kline?board_id={bid}&timeframe={tf}&limit=2",
                      token, timeout=10)
            bars = out.get("ohlcv") or []
            if len(bars) >= 1:
                return len(bars)
            last = out
        except Exception as exc:
            last = str(exc)
        time.sleep(1)
    raise RuntimeError(f"kline timeout {bid}:{tf}: {last}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8895")
    ap.add_argument("--token", default="")
    ap.add_argument("--out", default="/tmp/ak_soak_072_sessions.json")
    args = ap.parse_args()
    base, token = args.base, args.token or None

    if not wait_health(base):
        print("service not ready", file=sys.stderr)
        return 2

    sessions = []
    for bid, symbol in BOARDS:
        ensure_board(base, token, bid, symbol)
        for tf in TFS:
            wait_bars(base, token, bid, tf)
            try:
                out = req(base, "/api/paper/sessions", token, "POST", {
                    "board_id": bid, "timeframe": tf,
                    "script": "strategy/ma_cross",
                    "initial_cash": 10000.0,
                    "fee_bps": 5.0, "slippage_bps": 5.0,
                }, timeout=60)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                raise RuntimeError(f"create session {bid}:{tf} failed: {exc.code} {body[:300]}") from exc
            if out.get("error"):
                raise RuntimeError(f"create session {bid}:{tf}: {out['error']}")
            sid = out["session_id"]
            started = req(base, f"/api/paper/sessions/{sid}/start", token, "POST", {},
                          timeout=60)
            if started.get("status") != "running":
                raise RuntimeError(f"start session {sid}: {started}")
            sessions.append({"board_id": bid, "timeframe": tf, "session_id": sid,
                             "symbol": symbol})
            print(f"started {sid} {symbol} {tf}", flush=True)

    payload = {"created_at": int(time.time() * 1000), "base": base,
               "sessions": sessions}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"wrote {args.out} sessions={len(sessions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
