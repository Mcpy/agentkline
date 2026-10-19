"""振荡器族（Vela 0.8.4 `src/core/native-indicators/classics/oscillators.ts`）。

逐条移植 Vela 的 JS 实现：保留其递归种子（SMA seed）、NaN 重置窗口、
`Math.trunc` 取整、零除守卫等语义，不做四舍五入。

缺失值一律为 None（对应 JS NaN）；只输出 golden 中「可见」的 plot
（anchor、全透明辅助线不输出）。阈值级别由前端视觉规格负责，本模块
不产出 `levels`（不伪造）。
"""
from __future__ import annotations

import math

from . import mathlib as M

# ---------- 局部原语（mathlib 未提供的 JS 同名函数） ----------


def _swma(v):
    """对称加权均线 (a + 2b + 2c + d) / 6，四个值齐全才输出。"""
    out = [None] * len(v)
    for i in range(3, len(v)):
        a, b, c, d = v[i - 3], v[i - 2], v[i - 1], v[i]
        if M.finite(a) and M.finite(b) and M.finite(c) and M.finite(d):
            out[i] = (a + 2 * b + 2 * c + d) / 6
    return out


def _percent_rank(v, n):
    """近 n 个值中 <= 当前值的比例（百分比）；窗口必须全有效才输出。"""
    out = [None] * len(v)
    if n <= 0:
        return out
    for i in range(n, len(v)):
        x = v[i]
        if not M.finite(x):
            continue
        window = v[i - n:i]
        if any(not M.finite(y) for y in window):
            continue
        out[i] = 100 * sum(1 for y in window if y <= x) / n
    return out


def _tsi_ratio(src, long_len, short_len):
    """TSI/SMI 共用：动量双重 EMA 平滑后与绝对值平滑相比。"""
    mom = M.change(src)
    numer = M.ema(M.ema(mom, long_len), short_len)
    denom = M.ema(M.ema(M.mapv(mom, abs), long_len), short_len)
    return M.zipv(numer, denom, lambda a, b: 0 if b == 0 else a / b)


def _stoch_norm(v, n):
    """STC 的随机归一化：值在自身 n 窗口高低区间中的位置，区间为 0 时沿用上一值。"""
    lo = M.lowest(v, n)
    hi = M.highest(v, n)
    out = [None] * len(v)
    pct = None
    for i, x in enumerate(v):
        l, h = lo[i], hi[i]
        if not (M.finite(x) and M.finite(l) and M.finite(h)):
            continue
        if h > l:
            pct = 100 * (x - l) / (h - l)
        out[i] = pct
    return out


def _smooth_step(v, factor):
    """STC 的 %D 式递归平滑（首值直接取原值）。"""
    out = [None] * len(v)
    smoothed = None
    for i, x in enumerate(v):
        if not M.finite(x):
            continue
        smoothed = smoothed + factor * (x - smoothed) if smoothed is not None else x
        out[i] = smoothed
    return out


def _stochastic_lines(k, params):
    """%K（已平滑）与 %D，供 stochastic / stochastic-rsi 共用。"""
    return [M.line("%K", k), M.line("%D", M.sma(k, M.pi(params, "dLength", 3)))]


# ---------- 研究 ----------


def rsi(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    return {"lines": [M.line("RSI", M.rsi_series(src, M.pi(params, "length", 14)))]}


def stochastic(params, bars):
    raw = M.stoch(M.closes(bars), M.highs(bars), M.lows(bars), M.pi(params, "kLength", 14))
    k = M.sma(raw, M.pi(params, "kSmoothing", 3))
    return {"lines": _stochastic_lines(k, params)}


def stochastic_rsi(params, bars):
    r = M.rsi_series(M.source_values(bars, M.ps(params, "source", "Close")),
                     M.pi(params, "rsiLength", 14))
    k = M.sma(M.stoch(r, r, r, M.pi(params, "stochLength", 14)),
              M.pi(params, "kSmoothing", 3))
    return {"lines": _stochastic_lines(k, params)}


def macd(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    line = M.sub(M.ema(src, M.pi(params, "fastLength", 12)),
                 M.ema(src, M.pi(params, "slowLength", 26)))
    signal = M.ema(line, M.pi(params, "signalLength", 9))
    hist = M.sub(line, signal)
    return {"lines": [M.line("Histogram", hist),
                      M.line("MACD", line),
                      M.line("Signal", signal)]}


def ppo(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))

    def average(kind, v, n):
        return M.sma(v, n) if kind == "SMA" else M.ema(v, n)

    ma_kind = M.ps(params, "maType", "EMA")
    fast = average(ma_kind, src, M.pi(params, "fastLength", 12))
    slow = average(ma_kind, src, M.pi(params, "slowLength", 26))
    line = M.zipv(fast, slow, lambda f, s: None if s == 0 else (f - s) / s * 100)
    signal = average(M.ps(params, "signalType", "EMA"), line, M.pi(params, "signalLength", 9))
    lines = []
    if M.pb(params, "showHistogram", True):
        lines.append(M.line("Histogram", M.sub(line, signal)))
    lines.append(M.line("PPO Line", line))
    lines.append(M.line("Signal Line", signal))
    return {"lines": lines}


def awesome_oscillator(params, bars):
    hl2 = M.source_values(bars, "HL2")
    ao = M.sub(M.sma(hl2, 5), M.sma(hl2, 34))
    return {"lines": [M.line("AO", ao)]}


def commodity_channel_index(params, bars):
    n = M.pi(params, "length", 20)
    src = M.source_values(bars, M.ps(params, "source", "HLC3"))
    basis = M.sma(src, n)
    dev = M.mean_dev(src, n)
    values = [None] * len(src)
    for i, x in enumerate(src):
        b, d = basis[i], dev[i]
        if not (M.finite(b) and M.finite(d)):
            continue
        values[i] = 0 if d == 0 else (x - b) / (0.015 * d)
    return {"lines": [M.line("CCI", values)]}


def williams_percent_r(params, bars):
    n = M.pi(params, "length", 14)
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    hh = M.highest(M.highs(bars), n)
    ll = M.lowest(M.lows(bars), n)
    values = [None] * len(src)
    for i, x in enumerate(src):
        h, l = hh[i], ll[i]
        if M.finite(h) and M.finite(l) and h > l:
            values[i] = -100 * (h - x) / (h - l)
    return {"lines": [M.line("%R", values)]}


def chande_momentum_oscillator(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    return {"lines": [M.line("CMO", M.cmo(src, M.pi(params, "length", 9)))]}


def connors_rsi(params, bars):
    c = M.closes(bars)
    streak = [0.0] * len(c)
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]
        streak[i] = (max(streak[i - 1], 0) + 1 if d > 0
                     else min(streak[i - 1], 0) - 1 if d < 0 else 0)
    a = M.rsi_series(c, M.pi(params, "rsiLength", 3))
    b = M.rsi_series(streak, M.pi(params, "streakLength", 2))
    r = _percent_rank(M.roc(c, 1), M.pi(params, "rankLength", 100))
    values = [None] * len(c)
    for i in range(len(c)):
        x, y, z = a[i], b[i], r[i]
        if M.finite(x) and M.finite(y) and M.finite(z):
            values[i] = (x + y + z) / 3
    return {"lines": [M.line("Connors RSI", values)]}


def fisher_transform(params, bars):
    n = M.pi(params, "length", 9)
    hl2 = M.source_values(bars, "HL2")
    hi, lo = M.highest(hl2, n), M.lowest(hl2, n)
    out = [None] * len(bars)
    position = 0.0
    value = 0.0
    for i in range(len(bars)):
        h, l = hi[i], lo[i]
        if not (M.finite(h) and M.finite(l)):
            continue
        raw = (hl2[i] - l) / (h - l) - 0.5 if h > l else 0
        position = 0.66 * raw + 0.67 * position
        position = 0.999 if position > 0.99 else -0.999 if position < -0.99 else position
        value = 0.5 * math.log((1 + position) / (1 - position)) + 0.5 * value
        out[i] = value
    return {"lines": [M.line("Fisher", out), M.line("Trigger", M.shift(out, 1))]}


def trix(params, bars):
    n = M.pi(params, "length", 18)
    smooth = M.ema(M.ema(M.ema(M.closes(bars), n), n), n)
    values = M.roc(smooth, 1)
    signal = M.ema(values, M.pi(params, "signalLength", 9))
    return {"lines": [M.line("TRIX", values), M.line("Signal", signal)]}


def true_strength_index(params, bars):
    values = M.mapv(_tsi_ratio(M.closes(bars), M.pi(params, "longLength", 25),
                               M.pi(params, "shortLength", 13)), lambda x: 100 * x)
    signal = M.ema(values, M.pi(params, "signalLength", 13))
    return {"lines": [M.line("TSI", values), M.line("Signal", signal)]}


def smi_ergodic(params, bars):
    smi = _tsi_ratio(M.closes(bars), M.pi(params, "longLength", 20),
                     M.pi(params, "shortLength", 5))
    signal = M.ema(smi, M.pi(params, "signalLength", 5))
    if M.ps(params, "display", "Indicator") == "Oscillator":
        return {"lines": [M.line("Oscillator", M.sub(smi, signal))]}
    return {"lines": [M.line("SMI", smi), M.line("Signal", signal)]}


def schaff_trend_cycle(params, bars):
    n = M.pi(params, "cycleLength", 10)
    factor = M.pf(params, "factor", 0.5)
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    macd_line = M.sub(M.ema(src, M.pi(params, "fastLength", 23)),
                      M.ema(src, M.pi(params, "slowLength", 50)))
    values = _smooth_step(
        _stoch_norm(_smooth_step(_stoch_norm(macd_line, n), factor), n), factor)
    return {"lines": [M.line("Schaff Trend Cycle", values)]}


def know_sure_thing(params, bars):
    c = M.closes(bars)
    roc_defaults = (10, 15, 20, 30)
    sma_defaults = (10, 10, 10, 15)
    acc = [0.0] * len(c)
    for i in range(4):
        r = M.sma(M.roc(c, M.pi(params, f"rocLength{i + 1}", roc_defaults[i])),
                  M.pi(params, f"smaLength{i + 1}", sma_defaults[i]))
        weight = i + 1
        acc = M.zipv(acc, r, lambda a, b, w=weight: a + b * w)
    signal = M.sma(acc, M.pi(params, "signalLength", 9))
    return {"lines": [M.line("KST", acc), M.line("Signal", signal)]}


def coppock_curve(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    summed = M.zipv(M.roc(src, M.pi(params, "longRoc", 14)),
                    M.roc(src, M.pi(params, "shortRoc", 11)), lambda a, b: a + b)
    values = M.wma(summed, M.pi(params, "wmaLength", 10))
    return {"lines": [M.line("Coppock Curve", values)]}


def detrended_price_oscillator(params, bars):
    n = M.pi(params, "length", 21)
    back = math.trunc(n / 2) + 1
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    basis = M.sma(src, n)
    if M.pb(params, "centered", False):
        values = M.shift(M.sub(M.shift(src, back), basis), -back)
    else:
        values = M.sub(src, M.shift(basis, back))
    return {"lines": [M.line("DPO", values)]}


def rate_of_change(params, bars):
    n = M.pi(params, "length", 9)
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    values = M.change(src, n) if M.ps(params, "mode", "ROC %") == "Momentum" else M.roc(src, n)
    return {"lines": [M.line("ROC", values)]}


def ultimate_oscillator(params, bars):
    n = len(bars)
    bp = [None] * n
    tr = [None] * n
    for i, b in enumerate(bars):
        pc = bars[i - 1]["close"] if i > 0 else b["close"]
        true_low = min(b["low"], pc)
        bp[i] = b["close"] - true_low
        tr[i] = max(b["high"], pc) - true_low

    def avg(length):
        return M.zipv(M.sumv(bp, length), M.sumv(tr, length),
                      lambda a, b: None if b == 0 else a / b)

    a7 = avg(M.pi(params, "fastLength", 7))
    a14 = avg(M.pi(params, "middleLength", 14))
    a28 = avg(M.pi(params, "slowLength", 28))
    values = [None] * n
    for i in range(n):
        x, y, z = a7[i], a14[i], a28[i]
        if M.finite(x) and M.finite(y) and M.finite(z):
            values[i] = 100 * (4 * x + 2 * y + z) / 7
    return {"lines": [M.line("UO", values)]}


def relative_vigor_index(params, bars):
    n = M.pi(params, "length", 10)
    co = _swma(M.sub(M.closes(bars), M.opens(bars)))
    hl = _swma(M.sub(M.highs(bars), M.lows(bars)))
    line = M.zipv(M.sumv(co, n), M.sumv(hl, n), lambda a, b: 0 if b == 0 else a / b)
    return {"lines": [M.line("RVGI", line), M.line("Signal", _swma(line))]}


def relative_volatility_index(params, bars):
    c = M.closes(bars)
    sigma = M.stdev(c, M.pi(params, "stdevLength", 10))
    d = M.change(c)
    up = M.zipv(sigma, d, lambda s, x: s if x > 0 else 0)
    down = M.zipv(sigma, d, lambda s, x: s if x < 0 else 0)
    smooth_len = M.pi(params, "smoothLength", 14)
    smooth = M.rma if M.ps(params, "smoothType", "EMA") == "Wilder (RMA)" else M.ema
    values = M.zipv(smooth(up, smooth_len), smooth(down, smooth_len),
                    lambda u, w: 0 if u + w == 0 else 100 * u / (u + w))
    return {"lines": [M.line("RVI", values)]}


def balance_of_power(params, bars):
    raw = [0 if b["high"] == b["low"] else (b["close"] - b["open"]) / (b["high"] - b["low"])
           for b in bars]
    values = (M.sma(raw, M.pi(params, "smoothLength", 14))
              if M.pb(params, "smoothing", False) else raw)
    return {"lines": [M.line("BOP", values)]}


def elder_ray(params, bars):
    basis = M.ema(M.closes(bars), M.pi(params, "length", 13))
    return {"lines": [M.line("Bull Power", M.sub(M.highs(bars), basis)),
                      M.line("Bear Power", M.sub(M.lows(bars), basis))]}


def ttm_squeeze(params, bars):
    n = M.pi(params, "length", 20)
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    basis = M.sma(src, n)
    dev = M.mapv(M.stdev(src, n), lambda x: x * M.pf(params, "bbMult", 2))
    kc_range = M.mapv(M.atr(bars, n), lambda x: x * M.pf(params, "kcMult", 1.5))
    range_mid = M.zipv(M.highest(M.highs(bars), n), M.lowest(M.lows(bars), n),
                       lambda h, l: (h + l) / 2)
    anchor = M.zipv(range_mid, basis, lambda d, b: (d + b) / 2)
    mom = M.linreg(M.sub(src, anchor), n, 0)
    squeeze = []
    for i, b in enumerate(basis):
        d, r = dev[i], kc_range[i]
        if not (M.finite(b) and M.finite(d) and M.finite(r)):
            squeeze.append(None)
        else:
            squeeze.append(d < r)
    state = [None if s is None else 0 for s in squeeze]
    fires = [None] * len(bars)
    for i, s in enumerate(squeeze):
        if s is False and i > 0 and squeeze[i - 1] is True:
            fires[i] = 0
    lines = [M.line("Momentum", mom), M.line("Squeeze State", state)]
    if M.pb(params, "markFires", True):
        lines.append(M.line("Squeeze Fire", fires))
    return {"lines": lines}


STUDIES = {
    "rsi": rsi,
    "stochastic": stochastic,
    "stochastic-rsi": stochastic_rsi,
    "macd": macd,
    "ppo": ppo,
    "awesome-oscillator": awesome_oscillator,
    "commodity-channel-index": commodity_channel_index,
    "williams-percent-r": williams_percent_r,
    "chande-momentum-oscillator": chande_momentum_oscillator,
    "connors-rsi": connors_rsi,
    "fisher-transform": fisher_transform,
    "trix": trix,
    "true-strength-index": true_strength_index,
    "smi-ergodic": smi_ergodic,
    "schaff-trend-cycle": schaff_trend_cycle,
    "know-sure-thing": know_sure_thing,
    "coppock-curve": coppock_curve,
    "detrended-price-oscillator": detrended_price_oscillator,
    "rate-of-change": rate_of_change,
    "ultimate-oscillator": ultimate_oscillator,
    "relative-vigor-index": relative_vigor_index,
    "relative-volatility-index": relative_volatility_index,
    "balance-of-power": balance_of_power,
    "elder-ray": elder_ray,
    "ttm-squeeze": ttm_squeeze,
}
