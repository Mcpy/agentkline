"""通道/带状族（Vela bands.ts）。"""
from __future__ import annotations

from . import mathlib as M


def _bollinger(bars, params):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    n = M.pi(params, "length", 20)
    mult = M.pf(params, "mult", 2)
    basis = M.sma(src, n)
    dev = M.mapv(M.stdev(src, n), lambda x: x * mult)
    upper = M.zipv(basis, dev, lambda b, d: b + d)
    lower = M.zipv(basis, dev, lambda b, d: b - d)
    return src, basis, upper, lower


def bollinger_bands(params, bars):
    _, basis, upper, lower = _bollinger(bars, params)
    return {"lines": [M.line("Basis", basis), M.line("Upper", upper), M.line("Lower", lower)]}


def percent_b(params, bars):
    src, _, upper, lower = _bollinger(bars, params)
    values = [None] * len(src)
    for i, x in enumerate(src):
        u, l = upper[i], lower[i]
        if u is not None and l is not None and u != l:
            values[i] = (x - l) / (u - l)
    return {"lines": [M.line("%B", values)],
            "levels": [
                {"key": "overbought", "price": M.pf(params, "overbought", 1), "lineStyle": "dashed", "title": "Overbought"},
                {"key": "oversold", "price": M.pf(params, "oversold", 0), "lineStyle": "dashed", "title": "Oversold"},
                {"key": "midline", "price": 0.5, "lineStyle": "dotted", "title": "Midline"},
            ]}


def bandwidth(params, bars):
    _, basis, upper, lower = _bollinger(bars, params)
    values = [None] * len(basis)
    for i, b in enumerate(basis):
        u, l = upper[i], lower[i]
        if b is not None and b != 0 and u is not None and l is not None:
            values[i] = (u - l) / b
    look = M.pi(params, "lookback", 125)
    squeeze = M.lowest(values, look)
    bulge = M.highest(values, look)
    lines = [M.line("BandWidth", values),
             M.line("Zero Line", [0 if v is not None else None for v in values])]
    if M.pb(params, "showSqueeze", True):
        lines.append(M.line("Squeeze Level", squeeze))
    if M.pb(params, "showBulge", True):
        lines.append(M.line("Bulge Level", bulge))
    return {"lines": lines}


def keltner_channels(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    basis = M.ema(src, M.pi(params, "length", 20))
    mult = M.pf(params, "mult", 2)
    rng = M.mapv(M.atr(bars, M.pi(params, "atrLength", 10)), lambda x: x * mult)
    upper = M.zipv(basis, rng, lambda b, r: b + r)
    lower = M.zipv(basis, rng, lambda b, r: b - r)
    return {"lines": [M.line("Basis", basis), M.line("Upper", upper), M.line("Lower", lower)]}


def donchian_channels(params, bars):
    n = M.pi(params, "length", 20)
    upper = M.highest(M.highs(bars), n)
    lower = M.lowest(M.lows(bars), n)
    middle = M.zipv(upper, lower, lambda u, l: (u + l) / 2)
    return {"lines": [M.line("Upper", upper), M.line("Middle", middle, type="circles"), M.line("Lower", lower)]}


def chandelier_exit(params, bars):
    n = M.pi(params, "length", 22)
    mult = M.pf(params, "mult", 3)
    rng = M.mapv(M.atr(bars, n), lambda x: x * mult)
    basic_long = M.zipv(M.highest(M.highs(bars), n), rng, lambda h, r: h - r)
    basic_short = M.zipv(M.lowest(M.lows(bars), n), rng, lambda l, r: l + r)
    long, short = basic_long, basic_short
    if M.pb(params, "ratchet", False):
        long = [None] * len(bars)
        short = [None] * len(bars)
        for i, b in enumerate(bars):
            bl, bs = basic_long[i], basic_short[i]
            prev_close = bars[i - 1]["close"] if i > 0 else b["close"]
            prev_long = long[i - 1] if i > 0 and long[i - 1] is not None else bl
            prev_short = short[i - 1] if i > 0 and short[i - 1] is not None else bs
            long[i] = (max(bl, prev_long) if prev_close > prev_long else bl) if bl is not None else None
            short[i] = (min(bs, prev_short) if prev_close < prev_short else bs) if bs is not None else None
    return {"lines": [M.line("Long Stop", long), M.line("Short Stop", short)]}


def chande_kroll_stop(params, bars):
    pn = M.pi(params, "p", 10)
    q = M.pi(params, "q", 9)
    rng = M.mapv(M.atr(bars, pn), lambda v: v * M.pf(params, "x", 1))
    first_high = M.zipv(M.highest(M.highs(bars), pn), rng, lambda h, r: h - r)
    first_low = M.zipv(M.lowest(M.lows(bars), pn), rng, lambda l, r: l + r)
    return {"lines": [M.line("Stop Short", M.highest(first_high, q)),
                      M.line("Stop Long", M.lowest(first_low, q))]}


def supertrend(params, bars):
    mult = M.pf(params, "mult", 3)
    rng = M.atr(bars, M.pi(params, "atrLength", 10))
    n = len(bars)
    up = [None] * n
    down = [None] * n
    final_upper = final_lower = None
    trend = -1
    for i, b in enumerate(bars):
        r = rng[i]
        if r is None:
            continue
        mid = (b["high"] + b["low"]) / 2
        basic_upper = mid + mult * r
        basic_lower = mid - mult * r
        prev_upper = final_upper if final_upper is not None else basic_upper
        prev_lower = final_lower if final_lower is not None else basic_lower
        prev_close = bars[i - 1]["close"] if i > 0 else b["close"]
        final_upper = min(basic_upper, prev_upper) if prev_close <= prev_upper else basic_upper
        final_lower = max(basic_lower, prev_lower) if prev_close >= prev_lower else basic_lower
        trend = 1 if b["close"] > final_upper else -1 if b["close"] < final_lower else trend
        if trend == 1:
            up[i] = final_lower
        else:
            down[i] = final_upper
    return {"lines": [M.line("Uptrend", up), M.line("Downtrend", down)]}


def williams_alligator(params, bars):
    hl2 = M.source_values(bars, "HL2")
    jaw = M.shift(M.rma(hl2, M.pi(params, "jawLength", 13)), M.pi(params, "jawOffset", 8))
    teeth = M.shift(M.rma(hl2, M.pi(params, "teethLength", 8)), M.pi(params, "teethOffset", 5))
    lips = M.shift(M.rma(hl2, M.pi(params, "lipsLength", 5)), M.pi(params, "lipsOffset", 3))
    return {"lines": [M.line("Jaw", jaw), M.line("Teeth", teeth), M.line("Lips", lips)]}


def gator_oscillator(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "HL2"))
    kind = M.ps(params, "maType", "SMMA (Wilder)")

    def smooth(n):
        return M.sma(src, n) if kind == "SMA" else M.ema(src, n) if kind == "EMA" else M.rma(src, n)

    jaw = M.shift(smooth(M.pi(params, "jawLength", 13)), M.pi(params, "jawOffset", 8))
    teeth = M.shift(smooth(M.pi(params, "teethLength", 8)), M.pi(params, "teethOffset", 5))
    lips = M.shift(smooth(M.pi(params, "lipsLength", 5)), M.pi(params, "lipsOffset", 3))
    upper = M.mapv(M.sub(jaw, teeth), abs)
    lower = M.mapv(M.sub(teeth, lips), abs)
    return {"lines": [
        M.line("Upper Histogram (Jaw - Teeth)", upper, type="columns"),
        M.line("Lower Histogram (Teeth - Lips)", M.mapv(lower, lambda x: -x), type="columns"),
    ], "levels": [{"key": "zero", "price": 0, "lineStyle": "solid", "title": "Zero Line"}]}


STUDIES = {
    "bollinger-bands": bollinger_bands,
    "percent-b": percent_b,
    "bandwidth": bandwidth,
    "keltner-channels": keltner_channels,
    "donchian-channels": donchian_channels,
    "chandelier-exit": chandelier_exit,
    "chande-kroll-stop": chande_kroll_stop,
    "supertrend": supertrend,
    "williams-alligator": williams_alligator,
    "gator-oscillator": gator_oscillator,
}
