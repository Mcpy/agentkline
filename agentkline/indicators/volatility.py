"""波动率研究族（Vela 0.8.4 `classics/volatility.ts`）：
ATR / 历史波动率 / Chaikin 波动率 / Mass Index / 标准差 / Ulcer Index / Choppiness。

0.10.19 新增：收盘价波动率 / O-H-L-C 波动率 / 零趋势波动率 / 标准误差
（Vela volatilityCloseToClose / volatilityOhlc / volatilityZeroTrend / standardError）。
"""
from __future__ import annotations

import math

from . import mathlib as M

_DAY_MS = 86400000
# Vela volatilityOhlc 常量：Garman-Klass 实体权重与隔夜跳空权重。
_SESSION_BODY_WEIGHT = 2 * math.log(2) - 1
_OVERNIGHT_WEIGHT = 0.12


def _bar_time(bar: dict) -> int:
    """bar 时间（毫秒）；兼容 `timestamp` 与 golden 的 `time`。"""
    t = bar.get("timestamp")
    if t is None:
        t = bar["time"]
    return int(t)


def _elapsed_days(bars: list[dict]) -> M.Series:
    """Vela elapsedDays：相邻 bar 间隔天数；首根与间隔 <= 0 为缺失。"""
    out: M.Series = [None] * len(bars)
    for i in range(1, len(bars)):
        days = (_bar_time(bars[i]) - _bar_time(bars[i - 1])) / _DAY_MS
        if days > 0:
            out[i] = days
    return out


def _log_returns(v: M.Series) -> M.Series:
    """Vela logReturns：ln(cur/prev)；首根缺失，要求前后值均有限且 > 0。"""
    out: M.Series = [None] * len(v)
    for i in range(1, len(v)):
        cur, prev = v[i], v[i - 1]
        if M.finite(cur) and M.finite(prev) and cur > 0 and prev > 0:
            out[i] = math.log(cur / prev)
    return out


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


def volatility_close_to_close(params, bars):
    """Vela volatilityCloseToClose：对数收益的样本方差（n-1），按 daysPerYear 年化。"""
    n = M.pi(params, "length", 10)
    annual = M.pi(params, "daysPerYear", 252)
    returns = _log_returns(M.closes(bars))
    if n < 2:
        values: M.Series = [None] * len(bars)
    else:
        def fold(f: int, t: int) -> float:
            mean = sum(returns[f:t + 1]) / n
            return sum((returns[k] - mean) ** 2 for k in range(f, t + 1)) / (n - 1)

        variance = M.windowed(returns, n, fold)
        values = M.mapv(variance, lambda v: 100 * math.sqrt(max(v, 0) * annual))
    return {"lines": [M.line("Volatility", values)]}


def volatility_ohlc(params, bars):
    """Vela volatilityOhlc：Garman-Klass 类日方差估计，按 bar 间隔天数归一后年化。

    session = 0.5*ln(h/l)^2 - (2ln2-1)*ln(c/o)^2；marketClosed > 0 时再计入
    隔夜跳空项 0.12*ln(o/prevClose)^2/closed，两部分按开收盘时长占比加权。
    """
    n = M.pi(params, "length", 10)
    annual = M.pi(params, "daysPerYear", 252)
    closed = min(max(M.pf(params, "marketClosed", 0), 0), 0.999)
    days = _elapsed_days(bars)
    per_day: M.Series = [None] * len(bars)
    for i, b in enumerate(bars):
        elapsed = days[i]
        o, h, l, c = b["open"], b["high"], b["low"], b["close"]
        if elapsed is None or not (l > 0) or not (o > 0) or not (h > 0) or not (c > 0):
            continue
        rng = math.log(h / l)
        body = math.log(c / o)
        session = 0.5 * rng * rng - _SESSION_BODY_WEIGHT * body * body
        if closed == 0:
            per_day[i] = session / elapsed
        else:
            pc = bars[i - 1]["close"]
            if not (pc > 0):
                continue
            gap = math.log(o / pc)
            per_day[i] = (_OVERNIGHT_WEIGHT * gap * gap / closed
                          + (1 - _OVERNIGHT_WEIGHT) * session / (1 - closed)) / elapsed
    values = M.mapv(M.sma(per_day, n),
                    lambda v: 100 * math.sqrt(v * annual) if v * annual >= 0 else None)
    return {"lines": [M.line("Volatility", values)]}


def volatility_zero_trend(params, bars):
    """Vela volatilityZeroTrend：零均值假设，ln 收益平方按间隔天数归一后取均值年化。"""
    n = M.pi(params, "length", 10)
    annual = M.pi(params, "daysPerYear", 252)
    log_close = M.mapv(M.closes(bars), lambda x: math.log(x) if x > 0 else None)
    returns = M.sub(log_close, M.shift(log_close, 1))
    per_day = M.zipv(returns, _elapsed_days(bars), lambda r, e: r * r / e)
    values = M.mapv(M.sma(per_day, n),
                    lambda v: 100 * math.sqrt(v * annual) if v * annual >= 0 else None)
    return {"lines": [M.line("Volatility", values)]}


def standard_error(params, bars):
    """Vela standardError：窗口线性回归残差的标准误差 sqrt(SSE/(n-2))；n<3 全缺失。"""
    n = M.pi(params, "length", 14)
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    if n < 3:
        return {"lines": [M.line("Standard Error", [None] * len(src))]}
    sx = (n - 1) * n / 2
    sxx = (n - 1) * n * (2 * n - 1) / 6
    denom = n * sxx - sx * sx

    def fold(f: int, t: int) -> float:
        sy = sxy = 0.0
        for k in range(f, t + 1):
            sy += src[k]
            sxy += (k - f) * src[k]
        slope = (n * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n
        sse = sum((src[k] - (intercept + slope * (k - f))) ** 2 for k in range(f, t + 1))
        return math.sqrt(sse / (n - 2))

    return {"lines": [M.line("Standard Error", M.windowed(src, n, fold))]}


STUDIES = {
    "average-true-range": average_true_range,
    "historical-volatility": historical_volatility,
    "chaikin-volatility": chaikin_volatility,
    "mass-index": mass_index,
    "standard-deviation": standard_deviation,
    "ulcer-index": ulcer_index,
    "choppiness-index": choppiness_index,
    "volatility-close-to-close": volatility_close_to_close,
    "volatility-ohlc": volatility_ohlc,
    "volatility-zero-trend": volatility_zero_trend,
    "standard-error": standard_error,
}
