#!/usr/bin/env python3
"""模拟盘审计（0.7.3）：用原始 K 线复核事件账本里的决策/成交/权益，可附加对账。

用法：
    python tools/paper_audit.py --session-id pp_xxx
    python tools/paper_audit.py --session-id pp_xxx --base http://127.0.0.1:8765
    python tools/paper_audit.py --session-id pp_xxx --reconcile
    python tools/paper_audit.py --session-id pp_xxx --no-backfill

默认按事件账本首条/末条时间自动回补审计所需 K 线；不会启动/停止/修改
paper 会话或账本。--no-backfill 可禁用回补，只检查当前已有历史。
--reconcile 会额外跑一次 paper vs 回测对账。
退出码 0=全部可解释；1=发现不一致；2=审计/回补前置条件失败。
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
_TF_MS = {"m": 60_000, "h": 3_600_000, "d": 86_400_000,
          "w": 7 * 86_400_000, "M": 30 * 86_400_000}


def tf_span_ms(tf: str):
    try:
        n = int(str(tf)[:-1])
        return n * _TF_MS[str(tf)[-1]]
    except (ValueError, KeyError, IndexError):
        return None


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def post_json(url: str, payload: dict):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
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


def current_bars(base: str, board_id: str, tf: str, limit: int = 5000):
    q = urllib.parse.urlencode({"board_id": board_id, "timeframe": tf,
                                "limit": max(1, int(limit))})
    data = get_json(f"{base}/api/kline?{q}")
    return data.get("ohlcv") or []


def ensure_audit_history(base: str, sess: dict, events: list[dict],
                         max_calls: int = 30, chunk: int = 1000) -> dict:
    """Backfill only the history needed by the event ledger.

    The old audit assumed the in-memory K-line window still covered every
    event; after a restart it may only contain the latest 200 bars.  This
    computes the first event timestamp and prepends just enough chunks.
    """
    board_id, tf = sess["board_id"], sess["timeframe"]
    span = tf_span_ms(tf)
    stamps = []
    for ev in events:
        if ev.get("kind") not in ("decision", "equity", "fill"):
            continue
        try:
            stamps.append(int(ev["bar_ts"]))
        except (KeyError, TypeError, ValueError):
            continue
    if not stamps or not span:
        return {"needed": 0, "prepended": 0, "covered": True, "calls": 0}
    first_ts, last_ts = min(stamps), max(stamps)
    needed = int((last_ts - first_ts) / span) + 1
    # Check the exact first event bar, not just the earliest of a 5000-bar page:
    # a 1m two-week session can have far more than the page limit.
    if bar_at(base, board_id, tf, first_ts):
        return {"needed": needed, "first_event_ts": first_ts,
                "prepended": 0, "calls": 0, "covered": True}
    bq = urllib.parse.quote(board_id, safe="")
    tq = urllib.parse.quote(tf, safe="")
    prepended = calls = 0
    covered = False
    while calls < max_calls:
        limit = int(chunk) if calls else max(1, min(int(chunk), needed + 100))
        out = post_json(
            f"{base}/api/board/{bq}/timeframe/{tq}/backfill",
            {"limit": limit})
        n = int(out.get("prepended") or 0)
        calls += 1
        if n <= 0:
            break
        prepended += n
        if bar_at(base, board_id, tf, first_ts):
            covered = True
            break
    return {"needed": needed, "first_event_ts": first_ts,
            "prepended": prepended, "calls": calls, "covered": covered}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--reconcile", action="store_true",
                    help="额外跑一次 paper vs 回测对账")
    ap.add_argument("--no-backfill", action="store_true",
                    help="不自动回补审计所需历史")
    ap.add_argument("--backfill-max-calls", type=int, default=30,
                    help="最多回补调用次数（默认 30）")
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
    if not args.no_backfill:
        try:
            hist = ensure_audit_history(base, sess, events,
                                        max_calls=max(1, args.backfill_max_calls))
        except Exception as exc:  # noqa: BLE001
            print(f"审计历史回补失败: {exc}", file=sys.stderr)
            return 2
        if hist.get("calls"):
            print(f"回补: 需要约 {hist.get('needed')} 根 / 补入 {hist.get('prepended')} 根 / "
                  f"调用 {hist.get('calls')} 次")
        if not hist.get("covered"):
            print("❌ PAPER_AUDIT_HISTORY_INSUFFICIENT: 数据源无法覆盖第一条事件所需历史",
                  file=sys.stderr)
            return 2
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

    if args.reconcile:
        try:
            rep = post_json(f"{base}/api/paper/sessions/{sid}/reconcile", {})
        except Exception as exc:  # noqa: BLE001
            print(f"\n❌ 对账失败: {exc}")
            return 2
        if rep.get("error"):
            print(f"\n❌ 对账失败: {rep['error']}")
            return 2
        print(f"\n对账 verdict={rep.get('verdict')}  "
              f"coverage={rep.get('coverage')}")
        print(f"  paper: {rep.get('paper')}")
        print(f"  backtest: {rep.get('backtest')}")
        print(f"  diff: {rep.get('diff_counts')}")
        for x in rep.get("explanations") or []:
            print(f"  ℹ {x.get('code')}: {x.get('message')}")
        if rep.get("verdict") == "mismatch":
            print("  ❌ 对账不一致")
            return 1
        print("  ✅ 对账一致或差异可解释")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
