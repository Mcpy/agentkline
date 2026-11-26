#!/usr/bin/env python3
"""0.7.4 批次门禁 soak 建会话：5 常态（BTC 15m/1h/4h/1d/1w）+ 10 压力（1m × 10 标的）。

用法：
  .venv/bin/python tools/setup_soak_074.py --base http://127.0.0.1:8766 \
      --token <agent token> --out /tmp/ak_gate_074_sessions.json

只走 HTTP，不导入 agentkline（避免污染现场库）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_soak_072 import ensure_board, req, wait_bars  # noqa: E402

NORMAL = [("soak_btc", "BTC/USDT:USDT", ["15m", "1h", "4h", "1d", "1w"])]
PRESSURE_SYMBOLS = [
    ("soak_eth", "ETH/USDT:USDT"), ("soak_sol", "SOL/USDT:USDT"), ("soak_bnb", "BNB/USDT:USDT"),
    ("soak_xrp", "XRP/USDT:USDT"), ("soak_ada", "ADA/USDT:USDT"), ("soak_doge", "DOGE/USDT:USDT"),
    ("soak_link", "LINK/USDT:USDT"), ("soak_avax", "AVAX/USDT:USDT"), ("soak_dot", "DOT/USDT:USDT"),
    ("soak_ltc", "LTC/USDT:USDT"),
]


def wait_health(base, token, timeout=60):
    """agent 端口带 token 的 /api/config 探活（072 的 wait_health 不带 token，会 401）。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            req(base, "/api/config", token, timeout=3)
            return True
        except Exception:
            time.sleep(1)
    return False


def create_session(base, token, bid, tf):
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
    st = req(base, f"/api/paper/sessions/{sid}/start", token, "POST", {}, timeout=60)
    if st.get("error"):
        raise RuntimeError(f"start {sid}: {st['error']}")
    return sid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8766")
    ap.add_argument("--token", required=True)
    ap.add_argument("--out", default="/tmp/ak_gate_074_sessions.json")
    args = ap.parse_args()
    base, token = args.base, args.token

    if not wait_health(base, token):
        print("service not ready", file=sys.stderr)
        return 2
    sessions, done = [], 0

    # 常态组：一个 BTC 板 5 个周期
    for bid, symbol, tfs in NORMAL:
        # 板按 source+symbol 去重：同标的已存在时返回既有板 id，后续一律用它。
        real = ensure_board(base, token, bid, symbol)
        for tf in tfs:
            wait_bars(base, token, real, tf)
            sid = create_session(base, token, real, tf)
            sessions.append({"group": "normal", "board": real, "symbol": symbol,
                             "timeframe": tf, "session_id": sid})
            done += 1
            print(f"[{done}] normal {bid}:{tf} -> {sid}")

    # 压力组：10 标的 × 1m
    for bid, symbol in PRESSURE_SYMBOLS:
        real = ensure_board(base, token, bid, symbol)
        wait_bars(base, token, real, "1m")
        sid = create_session(base, token, real, "1m")
        sessions.append({"group": "pressure", "board": real, "symbol": symbol,
                         "timeframe": "1m", "session_id": sid})
        done += 1
        print(f"[{done}] pressure {bid}:1m -> {sid}")

    Path(args.out).write_text(json.dumps({"created_at": time.strftime("%F %T"),
                                          "base": base, "sessions": sessions},
                                         ensure_ascii=False, indent=1))
    print(f"written {args.out}: {len(sessions)} sessions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
