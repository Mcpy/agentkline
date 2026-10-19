"""波动率研究族（Vela 0.8.4 `classics/volatility.ts`）：
ATR / 历史波动率 / Chaikin 波动率 / Mass Index / 标准差 / Ulcer Index / Choppiness。
"""
from __future__ import annotations

import math

from . import mathlib as M


def average_true_range(params, bars):
    n = M.pi(params, "length", 14)
    tr = M.true_range(bars)
    kind = M.ps(params, "smoothing", "RMA")
    if kind == "SMA":
        values = M.sma(tr, n)
    elif kind == "EMA":
        values = M.ema(tr, n)
    elif kind == "WMA":
        values = M.wma(tr, n)
    else:
        values = M.rma(tr, n)
    return {"lines": [M.line("ATR", values)]}


def historical_volatility(params, bars):
    n = M.pi(params, "length", 10)
    log_closes = M.mapv(M.closes(bars), math.log)
    # 对数收益：首根缺前值；Vela 用 shift(1) 后 zip 相减。
    log_returns = M.sub(log_closes, M.shift(log_closes, 1))
    mean_return = M.mapv(M.sumv(log_returns, n), lambda s: s / n if n else None)
    squared_sum = M.sumv(M.mapv(log_returns, lambda r: r * r), n)
    factor = math.sqrt(M.pi(params, "periodsPerYear", 252)) if M.pb(params, "annualize", True) else 1

    def _vol(sq: float, mean: float):
        if n <= 1:
            # JS 中 n=1 时 (0)/0 得 NaN，最终不是有限值 → 缺失。
            return None
        return math.sqrt(max(sq - n * mean * mean, 0) / (n - 1)) * factor * 100

    values = M.zipv(squared_sum, mean_return, _vol)
    return {"lines": [M.line("Historical Volatility", values)]}


def chaikin_volatility(params, bars):
    ema_len = M.pi(params, "emaLength", 10)
    roc_len = M.pi(params, "rocLength", 10)
    rng = M.ema(M.sub(M.highs(bars), M.lows(bars)), ema_len)
    prior = M.shift(rng, roc_len)
    values = M.zipv(rng, prior, lambda r, p: None if p == 0 else 100 * (r - p) / p)
    return {
        "lines": [M.line("Chaikin Volatility", values)],
        "levels": [{"key": "zero", "price": 0, "lineStyle": "dashed", "title": "Zero Line"}],
    }


def mass_index(params, bars):
    ema_len = M.pi(params, "emaLength", 9)
    single = M.ema(M.sub(M.highs(bars), M.lows(bars)), ema_len)
    ratio = M.zipv(single, M.ema(single, ema_len), lambda a, b: 1 if b == 0 else a / b)
    values = M.sumv(ratio, M.pi(params, "length", 25))
    setup = M.pf(params, "setupLevel", 27)
    trigger = M.pf(params, "triggerLevel", 26.5)
    return {
        "lines": [M.line("Mass Index", values)],
        "levels": [
            {"key": "setup", "price": setup, "lineStyle": "dashed", "title": "Setup Level"},
            {"key": "trigger", "price": trigger, "lineStyle": "dashed", "title": "Trigger Level"},
        ],
    }


def standard_deviation(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    values = M.stdev(src, M.pi(params, "length", 20))
    return {"lines": [M.line("Standard Deviation", values)]}


def ulcer_index(params, bars):
    n = M.pi(params, "length", 14)
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    values: M.Series = [None] * len(src)
    drawdown: M.Series = [None] * len(src)
    if n > 0:
        for i in range(n - 1, len(src)):
            run_max = None
            sum_sq = 0.0
            last = None
            valid = True
            for k in range(i - n + 1, i + 1):
                price = src[k]
                if price is None:
                    valid = False
                    break
                run_max = price if run_max is None else max(run_max, price)
                if run_max <= 0:
                    valid = False
                    break
                last = 100 * (price - run_max) / run_max
                sum_sq += last * last
            if valid:
                values[i] = math.sqrt(sum_sq / n)
                drawdown[i] = last

    lines = [M.line("Ulcer Index", values)]
    if M.pb(params, "showDrawdown", False):
        lines.append(M.line("Drawdown %", drawdown))
    return {
        "lines": lines,
        "levels": [
            {"key": "zero", "price": 0, "lineStyle": "dotted", "title": "Zero Level"},
            {"key": "threshold", "price": M.pf(params, "threshold", 5), "lineStyle": "dashed", "title": "Alert Threshold"},
        ],
    }


def choppiness_index(params, bars):
    n = M.pi(params, "length", 14)
    tr_sum = M.sumv(M.true_range(bars), n)
    span = M.zipv(M.highest(M.highs(bars), n), M.lowest(M.lows(bars), n), lambda h, l: h - l)
    log_len = math.log10(n) if n > 0 else 0.0

    def _chop(t: float, s: float):
        if s <= 0 or t <= 0 or log_len == 0:
            return None
        return 100 * math.log10(t / s) / log_len

    values = M.zipv(tr_sum, span, _chop)
    return {
        "lines": [M.line("CHOP", values)],
        "levels": [
            {"key": "overbought", "price": M.pf(params, "upperBand", 61.8), "lineStyle": "dashed", "title": "Upper Band"},
            {"key": "oversold", "price": M.pf(params, "lowerBand", 38.2), "lineStyle": "dashed", "title": "Lower Band"},
        ],
    }


STUDIES = {
    "average-true-range": average_true_range,
    "historical-volatility": historical_volatility,
    "chaikin-volatility": chaikin_volatility,
    "mass-index": mass_index,
    "standard-deviation": standard_deviation,
    "ulcer-index": ulcer_index,
    "choppiness-index": choppiness_index,
}
