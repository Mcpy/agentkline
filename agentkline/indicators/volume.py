"""成交量族（Vela 0.8.4 `native-indicators/classics/volume.ts`）。

逐字对齐 JS 语义：
- 缺失值 = None（JS NaN）；滚动窗口遇到 None 会重置（`M.sumv`/`M.sma` 等）
- 累计线 `cumSum` 只累加有效值，一旦开始输出后遇缺口保持累加值（不重置）
- 除法守卫按 JS 原样：`v === 0`、`s > 0`、`prev === 0` 等
- 仅输出可见 plot；隐藏的 anchor（baseline/zone/obAnchor…）不输出
"""
from __future__ import annotations

import math
from typing import Optional

from . import mathlib as M

Series = list[Optional[float]]


# ---------- 局部数学辅助 ----------
def _cumsum(values: Series) -> Series:
    """JS cumSum：累加有效值；首次有效值之前为 None，之后缺口沿用累计值。"""
    out: Series = [None] * len(values)
    acc = 0.0
    seen = False
    for i, x in enumerate(values):
        if x is not None:
            acc += x
            seen = True
        if seen:
            out[i] = acc
    return out


def _money_flow_volume(bars: list[dict]) -> Series:
    """(2*close - high - low) / (high - low) * volume；high == low 记 0。"""
    out: Series = []
    for b in bars:
        v = b.get("volume")
        if v is None or not math.isfinite(v):
            out.append(None)
            continue
        h, l, c = b["high"], b["low"], b["close"]
        out.append(0.0 if h == l else (2 * c - h - l) / (h - l) * v)
    return out


def _volume_index(bars: list[dict], src: Series, base: float, when) -> Series:
    """NVI/PVI 共用：成交量满足 when 时按 src 的百分比变化复利累计。"""
    out: Series = [None] * len(bars)
    index = float(base)
    for i, b in enumerate(bars):
        v = b.get("volume")
        pv = bars[i - 1].get("volume") if i > 0 else None
        prev = src[i - 1] if i > 0 else None
        active = (v is not None and pv is not None
                  and math.isfinite(v) and math.isfinite(pv) and when(v, pv))
        if active and prev is not None and prev != 0:
            index *= 1 + (src[i] - prev) / prev
        out[i] = index
    return out


def _zero_level() -> list[dict]:
    return [{"key": "zero", "price": 0, "lineStyle": "dashed", "title": "Zero Line"}]


# ---------- 15 个研究 ----------
def on_balance_volume(params, bars):
    vol = M.volumes(bars)
    diff = M.change(M.closes(bars))
    contribution = M.zipv(vol, diff, lambda v, x: v if x > 0 else -v if x < 0 else 0)
    values = _cumsum(contribution)
    lines = [M.line("OBV", values)]
    if M.pb(params, "smoothing", False):
        length = M.pi(params, "maLength", 20)
        kind = M.ps(params, "maType", "SMA")
        if kind == "EMA":
            ma = M.ema(values, length)
        elif kind == "WMA":
            ma = M.wma(values, length)
        elif kind == "RMA (SMMA)":
            ma = M.rma(values, length)
        else:
            ma = M.sma(values, length)
        lines.append(M.line("Smoothing MA", ma))
    return {"lines": lines}


def accumulation_distribution(params, bars):
    values = _cumsum(_money_flow_volume(bars))
    return {"lines": [M.line("A/D", values)]}


def chaikin_money_flow(params, bars):
    length = M.pi(params, "length", 20)
    mfv = M.sumv(_money_flow_volume(bars), length)
    vol = M.sumv(M.volumes(bars), length)
    values = M.zipv(mfv, vol, lambda m, v: 0 if v == 0 else m / v)
    return {"lines": [M.line("CMF", values)], "levels": _zero_level()}


def chaikin_oscillator(params, bars):
    ad = _cumsum(_money_flow_volume(bars))
    fast = M.ema(ad, M.pi(params, "fastLength", 3))
    slow = M.ema(ad, M.pi(params, "slowLength", 10))
    values = M.sub(fast, slow)
    return {"lines": [M.line("Chaikin Oscillator", values)], "levels": _zero_level()}


def ease_of_movement(params, bars):
    divisor = M.pf(params, "divisor", 10000)
    move = M.change(M.source_values(bars, "HL2"))
    raw: Series = []
    for i, b in enumerate(bars):
        m = move[i]
        v = b.get("volume")
        if v is None or not math.isfinite(v) or m is None:
            raw.append(None)
        else:
            raw.append(0 if v == 0 else divisor * m * (b["high"] - b["low"]) / v)
    values = M.sma(raw, M.pi(params, "length", 14))
    return {"lines": [M.line("EOM", values)], "levels": _zero_level()}


def force_index(params, bars):
    raw = M.zipv(M.change(M.closes(bars)), M.volumes(bars), lambda d, v: d * v)
    values = M.ema(raw, M.pi(params, "length", 13))
    return {"lines": [M.line("Force Index", values)], "levels": _zero_level()}


def klinger_oscillator(params, bars):
    n = len(bars)
    force: Series = [None] * n
    trend = 1
    prev_trend = 1
    cm = 0.0
    prev_dm = 0.0
    for i, b in enumerate(bars):
        hlc = b["high"] + b["low"] + b["close"]
        prev_b = bars[i - 1] if i > 0 else b
        prev_hlc = prev_b["high"] + prev_b["low"] + prev_b["close"]
        trend = 1 if hlc > prev_hlc else -1
        dm = b["high"] - b["low"]
        cm = cm + dm if i > 0 and trend == prev_trend else prev_dm + dm
        v = b.get("volume")
        if v is None or not math.isfinite(v):
            force[i] = None
        else:
            force[i] = 0 if cm == 0 else v * abs(2 * (dm / cm) - 1) * trend * 100
        prev_trend = trend
        prev_dm = dm
    values = M.sub(M.ema(force, M.pi(params, "fastLength", 34)),
                   M.ema(force, M.pi(params, "slowLength", 55)))
    signal = M.ema(values, M.pi(params, "signalLength", 13))
    return {"lines": [M.line("KVO", values), M.line("Signal", signal)], "levels": _zero_level()}


def money_flow_index(params, bars):
    length = M.pi(params, "length", 14)
    typical = M.source_values(bars, "HLC3")
    raw_flow = M.zipv(typical, M.volumes(bars), lambda p, v: p * v)
    diff = M.change(typical)
    pos = M.sumv(M.zipv(raw_flow, diff, lambda f, x: f if x > 0 else 0), length)
    neg = M.sumv(M.zipv(raw_flow, diff, lambda f, x: f if x < 0 else 0), length)
    values = M.zipv(pos, neg, lambda p, w: 100 * p / (p + w) if p + w > 0 else None)
    return {
        "lines": [M.line("MFI", values)],
        "levels": [
            {"key": "overbought", "price": M.pf(params, "overbought", 80), "lineStyle": "dashed", "title": "Overbought"},
            {"key": "oversold", "price": M.pf(params, "oversold", 20), "lineStyle": "dashed", "title": "Oversold"},
        ],
    }


def negative_volume_index(params, bars):
    values = _volume_index(bars, M.closes(bars), M.pf(params, "base", 1000), lambda v, pv: v < pv)
    signal = M.ema(values, M.pi(params, "signalLength", 255))
    return {"lines": [M.line("Signal EMA", signal), M.line("NVI", values)]}


def positive_volume_index(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    values = _volume_index(bars, src, M.pf(params, "base", 1000), lambda v, pv: v > pv)
    signal = M.ema(values, M.pi(params, "signalLength", 255))
    return {"lines": [M.line("Signal EMA", signal), M.line("PVI", values)]}


def price_volume_trend(params, bars):
    closes = M.closes(bars)
    raw: Series = []
    for i, b in enumerate(bars):
        v = b.get("volume")
        if i == 0 or v is None or not math.isfinite(v):
            raw.append(None)
            continue
        pc = closes[i - 1]
        raw.append(0 if pc == 0 else (closes[i] - pc) / pc * v)
    values = _cumsum(raw)
    lines = [M.line("PVT", values)]
    if M.pb(params, "showSignal", False):
        length = M.pi(params, "signalLength", 21)
        signal = M.ema(values, length) if M.ps(params, "signalType", "SMA") == "EMA" else M.sma(values, length)
        lines.append(M.line("Signal", signal))
    return {"lines": lines}


def volume_oscillator(params, bars):
    vol = M.volumes(bars)
    fast = M.ema(vol, M.pi(params, "fastLength", 5))
    slow = M.ema(vol, M.pi(params, "slowLength", 10))
    values = M.zipv(fast, slow, lambda f, s: 0 if s == 0 else 100 * (f - s) / s)
    return {"lines": [M.line("Volume Oscillator", values)], "levels": _zero_level()}


def pvo(params, bars):
    vol = M.volumes(bars)
    fast = M.ema(vol, M.pi(params, "fastLength", 12))
    slow = M.ema(vol, M.pi(params, "slowLength", 26))
    values = M.zipv(fast, slow, lambda f, s: 100 * (f - s) / s if s > 0 else None)
    signal = M.ema(values, M.pi(params, "signalLength", 9))
    lines = [M.line("PVO", values)]
    if M.pb(params, "showHistogram", True):
        lines.append(M.line("Histogram", M.sub(values, signal), type="columns"))
    if M.pb(params, "showSignal", True):
        lines.append(M.line("Signal", signal))
    return {"lines": lines, "levels": _zero_level()}


def volume_flow_indicator(params, bars):
    length = M.pi(params, "length", 130)
    typical = M.source_values(bars, "HLC3")
    log_series = M.mapv(typical, math.log)
    log_change = M.sub(log_series, M.shift(log_series, 1))
    volatility = M.stdev(log_change, M.pi(params, "volLength", 30))
    coef = M.pf(params, "coef", 0.2)
    vol_coef = M.pf(params, "volCoef", 2.5)
    vol = M.volumes(bars)
    avg_volume = M.shift(M.sma(vol, length), 1)
    typical_change = M.change(typical)
    signed: Series = []
    for i, b in enumerate(bars):
        sd, m, v = volatility[i], typical_change[i], vol[i]
        if sd is None or m is None or v is None:
            signed.append(None)
            continue
        cutoff = coef * sd * b["close"]
        avg = avg_volume[i]
        capped = min(v, avg * vol_coef) if avg is not None else v
        signed.append(capped if m > cutoff else -capped if m < -cutoff else 0)
    raw = M.zipv(M.sumv(signed, length), avg_volume, lambda f, a: f / a if a > 0 else None)
    values = M.ema(raw, M.pi(params, "smoothLength", 3)) if M.pb(params, "smooth", True) else raw
    lines = [M.line("VFI", values)]
    if M.pb(params, "showSignal", True):
        lines.append(M.line("Signal Line", M.ema(values, M.pi(params, "signalLength", 5))))
    return {"lines": lines, "levels": _zero_level()}


def intraday_intensity(params, bars):
    intensity = _money_flow_volume(bars)
    if M.ps(params, "mode", "Normalized Oscillator (II%)") == "Cumulative Line":
        return {"lines": [M.line("Intraday Intensity", _cumsum(intensity))]}
    length = M.pi(params, "length", 21)
    mfv = M.sumv(intensity, length)
    vol = M.sumv(M.volumes(bars), length)
    values = M.zipv(mfv, vol, lambda m, v: 100 * m / v if v > 0 else None)
    return {"lines": [M.line("Intraday Intensity", values)], "levels": _zero_level()}


STUDIES = {
    "on-balance-volume": on_balance_volume,
    "accumulation-distribution": accumulation_distribution,
    "chaikin-money-flow": chaikin_money_flow,
    "chaikin-oscillator": chaikin_oscillator,
    "ease-of-movement": ease_of_movement,
    "force-index": force_index,
    "klinger-oscillator": klinger_oscillator,
    "money-flow-index": money_flow_index,
    "negative-volume-index": negative_volume_index,
    "positive-volume-index": positive_volume_index,
    "price-volume-trend": price_volume_trend,
    "volume-oscillator": volume_oscillator,
    "pvo": pvo,
    "volume-flow-indicator": volume_flow_indicator,
    "intraday-intensity": intraday_intensity,
}
