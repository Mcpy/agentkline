"""统计口径（与主包 0.6.0 `results.compute_stats_full` 逐字段一致）。

core 不 import 主包，所以这里是一份纯函数副本；一致性由 `tests/test_metrics_parity.py`
对照主包实现守护（1e-12）。
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right

YEAR_MS = 365 * 86400 * 1000


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _to_ms(v):
    if v is None:
        return None
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n * 1000 if abs(n) < 10 ** 11 else n


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs):
    """样本标准差（ddof=1）；不足两个样本返回 0。"""
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _returns(values):
    return [values[i] / values[i - 1] - 1 for i in range(1, len(values))
            if values[i - 1] not in (0, None) and values[i] is not None]


def compute_stats(equity, trades, initial_cash, bpy=None, benchmark=None) -> dict:
    values = [v for v in equity if v is not None]
    n = len(values)
    init = _num(initial_cash) or (values[0] if values else 0.0)
    out = {
        "final_value": values[-1] if values else init,
        "total_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0,
        "volatility": 0.0, "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0,
        "win_rate": 0.0, "profit_loss_ratio": None, "profit_factor": None,
        "max_consecutive_loss": 0, "trade_count": len(trades or []),
        "execution_count": None, "avg_holding_bars": 0.0, "exposure": 0.0,
        "total_fees": 0.0, "benchmark_return": None, "excess_return": None,
        "information_ratio": None, "tracking_error": None, "benchmark_beta": None,
    }
    if n == 0:
        return out

    total = (values[-1] / init - 1) if init else 0.0
    out["total_return"] = total
    periods = max(n - 1, 1)
    growth = 1 + total
    if growth <= 0:
        ann = -1.0
    else:
        try:
            ann = growth ** ((bpy or 365) / periods) - 1
        except OverflowError:
            ann = float("inf")
    out["annual_return"] = ann if math.isfinite(ann) else None

    rets = _returns(values)
    if len(rets) > 1:
        vol = _std(rets)
        out["volatility"] = vol * math.sqrt(bpy or 365)
        if vol > 1e-12:
            out["sharpe"] = _mean(rets) / vol * math.sqrt(bpy or 365)
        down = math.sqrt(sum(min(r, 0.0) ** 2 for r in rets) / len(rets))
        if down > 1e-12:
            out["sortino"] = _mean(rets) / down * math.sqrt(bpy or 365)
    if not math.isfinite(out["sharpe"] or 0):
        out["sharpe"] = 0.0
    if not math.isfinite(out["sortino"] or 0):
        out["sortino"] = 0.0

    peak = init
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            max_dd = min(max_dd, v / peak - 1)
    out["max_drawdown"] = max_dd
    if abs(max_dd) > 1e-12 and out["annual_return"] is not None:
        out["calmar"] = out["annual_return"] / abs(max_dd)
        if not math.isfinite(out["calmar"]):
            out["calmar"] = 0.0

    pnls = [_num(t.get("pnl")) for t in (trades or [])]
    pnls = [p for p in pnls if p is not None]
    if pnls:
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        out["win_rate"] = len(wins) / len(pnls)
        if losses:
            avg_win = _mean(wins) if wins else 0.0
            avg_loss = abs(_mean(losses))
            gross_loss = abs(sum(losses))
            if avg_loss > 1e-12:
                out["profit_loss_ratio"] = avg_win / avg_loss
            if gross_loss > 1e-12:
                out["profit_factor"] = (sum(wins) if wins else 0.0) / gross_loss
        consec = cur = 0
        for p in pnls:
            if p < 0:
                cur += 1
                consec = max(consec, cur)
            else:
                cur = 0
        out["max_consecutive_loss"] = consec
    holds = [_num(t.get("holding_bars")) for t in (trades or [])]
    holds = [h for h in holds if h is not None and h >= 0]
    if holds:
        out["avg_holding_bars"] = _mean(holds)
    fees = [_num(t.get("fee")) for t in (trades or [])]
    out["total_fees"] = sum(f for f in fees if f is not None)
    out["trade_count"] = len(trades or [])

    return out


def compute_stats_full(equity_times, equity_values, trades, initial_cash, bpy=None,
                       benchmark=None, fills=None) -> dict:
    out = compute_stats(equity_values, trades, initial_cash, bpy, benchmark)
    n = len(equity_values)
    if fills is not None:
        out["execution_count"] = len(fills)

    if equity_times and trades:
        marks = [False] * len(equity_times)
        for t in trades:
            a = _to_ms(t.get("entry_time"))
            b = _to_ms(t.get("exit_time"))
            if a is None or b is None:
                continue
            i = bisect_left(equity_times, min(a, b))
            j = bisect_right(equity_times, max(a, b))
            for k in range(max(0, i), min(n, j)):
                marks[k] = True
        out["exposure"] = (sum(marks) / n) if n else 0.0

    if equity_times:
        for t in trades:
            if t.get("holding_bars") is None:
                a, b = _to_ms(t.get("entry_time")), _to_ms(t.get("exit_time"))
                if a is not None and b is not None:
                    t["holding_bars"] = max(0, bisect_left(equity_times, max(a, b))
                                             - bisect_left(equity_times, min(a, b)))

    holds = [t.get("holding_bars") for t in trades
             if t.get("holding_bars") is not None and t.get("holding_bars") >= 0]
    out["avg_holding_bars"] = (sum(holds) / len(holds)) if holds else 0.0

    if benchmark and benchmark.get("values") and len(benchmark["values"]) > 1:
        bvals = benchmark["values"]
        out["benchmark_return"] = bvals[-1] / bvals[0] - 1 if bvals[0] else 0.0
        out["excess_return"] = out["total_return"] - out["benchmark_return"]
        bmap = dict(zip(benchmark.get("times") or [], bvals))
        pairs = []
        for i in range(1, len(equity_times)):
            ta, tb = equity_times[i - 1], equity_times[i]
            if ta in bmap and tb in bmap and bmap[ta] and equity_values[i - 1]:
                pairs.append((equity_values[i] / equity_values[i - 1] - 1,
                              bmap[tb] / bmap[ta] - 1))
        if len(pairs) > 1:
            active = [p[0] - p[1] for p in pairs]
            te = _std(active)
            out["tracking_error"] = te * math.sqrt(bpy or 365)
            if te > 1e-12:
                out["information_ratio"] = _mean(active) / te * math.sqrt(bpy or 365)
            bmean = _mean([p[1] for p in pairs])
            bvar = sum((p[1] - bmean) ** 2 for p in pairs) / (len(pairs) - 1)
            if bvar > 1e-15:
                cov = sum((p[0] - _mean([x[0] for x in pairs])) * (p[1] - bmean)
                          for p in pairs) / (len(pairs) - 1)
                out["benchmark_beta"] = cov / bvar
    return out


def observed_bars_per_year(times) -> float:
    """观测密度：用首尾时间跨度算每年 bar 数；样本 <30 回退中位间隔。"""
    n = len(times or [])
    if n < 2:
        return 365.0
    span = int(times[-1]) - int(times[0])
    if n >= 30 and span > 0:
        return (n - 1) / (span / YEAR_MS)
    diffs = sorted(int(times[i]) - int(times[i - 1]) for i in range(1, n))
    med = diffs[len(diffs) // 2]
    if med <= 0:
        return 365.0
    return YEAR_MS / med
