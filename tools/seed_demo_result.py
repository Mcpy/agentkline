#!/usr/bin/env python3
"""给演示环境塞一份结果（0.6.0 UI 验证用）。

用法：python tools/seed_demo_result.py --base http://127.0.0.1:18766 --token <token> \
        --board demo --timeframe 1d --name "演示 · 双均线"
"""
import argparse
import json
import urllib.request


def _get(url, token=None):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _post(url, payload, token=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def build(bars, name):
    closes = [float(b["close"]) for b in bars]
    times = [int(b["timestamp"]) for b in bars]
    fast, slow, fee = 10, 30, 0.001
    n = len(closes)
    ma = lambda i, w: sum(closes[i - w + 1:i + 1]) / w if i >= w - 1 else None
    pos = 0
    entry_i = None
    equity = [10000.0]
    trades = []
    fills = []
    for i in range(1, n):
        f, s = ma(i, fast), ma(i, slow)
        want = 1 if (f is not None and s is not None and f > s) else 0
        if want != pos:
            if want == 1:
                entry_i = i
                fills.append({"time": times[i], "action": "open", "signed_qty": 1.0,
                              "price": closes[i], "fee": 10000 * fee, "reason": "ma_cross_up"})
            else:
                pnl = (closes[i] - closes[entry_i]) * (10000 / closes[entry_i]) - 10000 * fee * 2
                trades.append({
                    "id": f"t{len(trades) + 1}", "side": "long",
                    "entry_time": times[entry_i], "exit_time": times[i],
                    "entry_price": closes[entry_i], "exit_price": closes[i],
                    "size": 10000 / closes[entry_i], "notional": 10000.0,
                    "fee": 10000 * fee * 2,
                    "pnl": pnl, "pnl_pct": pnl / 10000,
                    "holding_bars": i - entry_i,
                    "entry_reason": "ma_cross_up", "exit_reason": "ma_cross_down",
                })
                fills.append({"time": times[i], "action": "close", "signed_qty": -1.0,
                              "price": closes[i], "fee": 10000 * fee, "reason": "ma_cross_down"})
            pos = want
        equity.append(equity[-1] * (1 + (closes[i] / closes[i - 1] - 1) * pos))
    return {
        "display_name": name,
        "source": "external",
        "equity": {"times": times, "values": equity},
        "trades": trades,
        "fills": fills,
        "strategy": {"id": "strategy/demo_ma", "mode": "signal",
                     "params": {"fast": fast, "slow": slow},
                     "warmup": slow, "protection": {"stop_loss_pct": 0.05}},
        "engine": {"id": "external", "version": "demo", "license": "n/a",
                   "caps": {"signal": True, "event": False, "leverage": False}},
        "run": {"initial_cash": 10000, "fee": fee, "slippage": 0.0,
                "leverage": 1.0, "bars_per_year": 365},
        "execution_assumptions": {
            "fill_rule": "next_open", "bar_close_policy": "closed_only",
            "intrabar_mode": "conservative", "protection_rule": "gap_then_intrabar",
            "funding_mode": "not_modeled", "leverage": 1.0,
            "lot_policy": "continuous", "corporate_actions": "not_applied",
            "shorting": "unsupported",
            "notes": ["演示数据：MA(10/30) 交叉信号", "信号收盘确认，简化按当根收盘记账"],
        },
        "units": {"quantity": "BTC", "currency": "USDT"},
        "benchmark": {"id": "buy_hold", "times": times,
                      "values": [10000 * c / closes[0] for c in closes]},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:18766")
    ap.add_argument("--web", default="http://127.0.0.1:18765")
    ap.add_argument("--token", default="")
    ap.add_argument("--board", default="demo")
    ap.add_argument("--timeframe", default="1d")
    ap.add_argument("--name", default="演示 · 双均线")
    args = ap.parse_args()

    kl = _get(f"{args.web}/api/kline?board_id={args.board}&timeframe={args.timeframe}", args.token)
    bars = kl.get("ohlcv") or []
    if not bars:
        raise SystemExit("no bars; create the board first")
    payload = build(bars, args.name)
    payload["board_id"] = args.board
    payload["timeframe"] = args.timeframe
    out = _post(f"{args.base}/api/result", {"payload": payload}, args.token)
    print(json.dumps(out, ensure_ascii=False, indent=2)[:1200])


if __name__ == "__main__":
    main()
