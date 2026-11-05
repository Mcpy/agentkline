#!/usr/bin/env python3
"""模拟盘审计（0.7.0）：用原始 K 线复核事件账本里的决策/成交/权益。

用法：
    python tools/paper_audit.py --session-id pp_xxx
    python tools/paper_audit.py --session-id pp_xxx --base http://127.0.0.1:8765

只读：不启动/停止/修改会话。退出码 0=全部可解释；1=发现不一致。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request

TOL_PRICE = 1e-8
TOL_EQ = 1e-6
PROTECTION_REASONS = {"stop_loss", "take_profit"}


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_events(base: str, sid: str) -> list[dict]:
    out, after = [], 0
    while True:
        q = urllib.parse.urlencode({"after_seq": after, "limit": 1000})
        data = get_json(f"{base}/api/paper/sessions/{sid}/events?{q}")
        items = data.get("items") or []
        out.extend(items)
        if not data.get("truncated") or not items:
            return out
        after = int(data.get("next_after_seq") or after)


def bar_at(base: str, board_id: str, tf: str, ts: int):
    q = urllib.parse.urlencode({"board_id": board_id, "timeframe": tf,
                                "start": ts, "end": ts})
    data = get_json(f"{base}/api/kline?{q}")
    for bar in (data.get("ohlcv") or []):
        if int(bar["timestamp"]) == int(ts):
            return bar
    return None


def close_enough(a, b, tol) -> bool:
    return abs(float(a) - float(b)) <= max(tol, abs(float(b)) * tol)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    sid = args.session_id
    try:
        sess = get_json(f"{base}/api/paper/sessions/{sid}")
        events = fetch_events(base, sid)
    except Exception as exc:  # noqa: BLE001
        print(f"读取失败: {exc}", file=sys.stderr)
        return 2

    board_id, tf = sess["board_id"], sess["timeframe"]
    fee_bps = float(sess.get("fee_bps") or 0)
    slip = float(sess.get("slippage_bps") or 0) / 10_000.0
    bars = {}
    errors = []
    checks = 0

    def bar(ts):
        ts = int(ts)
        if ts not in bars:
            bars[ts] = bar_at(base, board_id, tf, ts)
        return bars[ts]

    decisions = fills = eqs = 0
    last_decision_ts = None
    last_equity_ts = None
    last_equity = None

    for ev in events:
        kind, payload, bts = ev.get("kind"), ev.get("payload") or {}, ev.get("bar_ts")
        if kind == "decision":
            decisions += 1
            last_decision_ts = bts
            b = bar(bts)
            if not b:
                errors.append(f"seq {ev['seq']}: decision bar 缺失 ts={bts}")
                continue
            checks += 1
            if "close" in payload and not close_enough(payload["close"], b["close"], TOL_PRICE):
                errors.append(f"seq {ev['seq']}: decision close {payload['close']} != bar {b['close']}")
        elif kind == "fill":
            fills += 1
            b = bar(bts)
            if not b:
                errors.append(f"seq {ev['seq']}: fill bar 缺失 ts={bts}")
                continue
            reason = str(payload.get("reason") or "")
            if reason in PROTECTION_REASONS:
                # 保护单可能按 open/触发价成交，价格由 high/low 决定；这里只检查落在 bar 范围内
                checks += 1
                px = float(payload.get("price") or 0)
                if not (float(b["low"]) - TOL_PRICE <= px <= float(b["high"]) + TOL_PRICE):
                    errors.append(f"seq {ev['seq']}: protection fill {px} 不在 [{b['low']},{b['high']}]")
                continue
            qty = float(payload.get("signed_qty") or 0)
            want = float(b["open"]) * (1 + slip if qty > 0 else 1 - slip)
            checks += 1
            if not close_enough(payload.get("price"), want, TOL_PRICE):
                errors.append(
                    f"seq {ev['seq']}: fill {payload.get('price')} != next-open {want} "
                    f"(bar open={b['open']}, qty={qty})")
            fee_want = abs(qty) * want * (fee_bps / 10_000.0)
            checks += 1
            if not close_enough(payload.get("fee"), fee_want, TOL_PRICE):
                errors.append(f"seq {ev['seq']}: fee {payload.get('fee')} != {fee_want}")
        elif kind == "equity":
            eqs += 1
            last_equity_ts = bts
            last_equity = payload.get("equity")
            b = bar(bts)
            if not b:
                errors.append(f"seq {ev['seq']}: equity bar 缺失 ts={bts}")
                continue
            checks += 1
            want = float(payload.get("cash") or 0) + float(payload.get("pos") or 0) * float(b["close"])
            if not close_enough(payload.get("equity"), want, TOL_EQ):
                errors.append(
                    f"seq {ev['seq']}: equity {payload.get('equity')} != cash+pos*close {want} "
                    f"(bar close={b['close']})")

    if sess.get("cursor_ts") is not None and last_decision_ts is not None \
            and int(sess["cursor_ts"]) != int(last_decision_ts):
        errors.append(f"cursor_ts {sess['cursor_ts']} != 最后 decision {last_decision_ts}")
    if sess.get("last_seen_ts") is not None and last_equity_ts is not None \
            and int(sess["last_seen_ts"]) != int(last_equity_ts):
        errors.append(f"last_seen_ts {sess['last_seen_ts']} != 最后 equity {last_equity_ts}")
    if last_equity is not None and sess.get("equity") is not None \
            and not close_enough(sess["equity"], last_equity, TOL_EQ):
        errors.append(f"session.equity {sess['equity']} != 最后 equity {last_equity}")

    print(f"session {sid}  status={sess.get('status')}  {board_id} {tf}")
    print(f"events={len(events)} decisions={decisions} fills={fills} equity={eqs} checks={checks}")
    if errors:
        print(f"\n发现 {len(errors)} 处不一致：")
        for e in errors:
            print("  ❌ " + e)
        return 1
    print("\n✅ 事件账本与原始 K 线一致（决策 close / next-open 成交 / 权益逐点）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
