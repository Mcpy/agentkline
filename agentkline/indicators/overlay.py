"""覆盖层族（Vela 0.8.4 `classics/overlays.ts`）。

逐字对齐原生实现：初始状态、NaN 传播、时间锚点与结构输出
（markers / polylines）都按 JS 原样移植。
"""
from __future__ import annotations

import datetime as _dt
import math
from collections import deque
from typing import Optional

from . import mathlib as M

DAY_MS = 86400000

Series = list[Optional[float]]


# ---------- Vela 时间锚点 ----------
def _time(bar: dict) -> int:
    """bar 时间（毫秒）；同时兼容 `timestamp` 与 golden 的 `time`。"""
    t = bar.get("timestamp")
    if t is None:
        t = bar["time"]
    return int(t)


def _utc(ms: int) -> _dt.datetime:
    return _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc) + _dt.timedelta(milliseconds=ms)


def _period_key(anchor: str, time: int) -> int:
    """Vela periodKey：按锚点把毫秒时间映射到周期键。"""
    if anchor == "Week":
        return (math.floor(time / DAY_MS) + 3) // 7
    if anchor in ("Month", "Quarter", "Year"):
        d = _utc(time)
        if anchor == "Year":
            return d.year
        if anchor == "Quarter":
            return d.year * 4 + (d.month - 1) // 3
        return d.year * 12 + (d.month - 1)
    return math.floor(time / DAY_MS)


def _bar_interval(bars: list[dict]) -> int:
    """Vela barInterval：相邻时间差的中位数（排序后取 floor(len/2)）。"""
    if len(bars) < 2:
        return 0
    gaps = sorted(_time(bars[i]) - _time(bars[i - 1]) for i in range(1, len(bars)))
    return gaps[len(gaps) // 2] if gaps else 0


# ---------- Parabolic SAR ----------
def parabolic_sar(params, bars):
    start = M.pf(params, "start", 0.02)
    inc = M.pf(params, "increment", 0.02)
    maximum = M.pf(params, "maximum", 0.2)
    n = len(bars)
    values: Series = [None] * n
    if n >= 2:
        long = bars[1]["close"] >= bars[0]["close"]
        sar = bars[0]["low"] if long else bars[0]["high"]
        ep = bars[0]["high"] if long else bars[0]["low"]
        af = start
        for i in range(1, n):
            b = bars[i]
            sar += af * (ep - sar)
            if long:
                sar = min(sar, bars[i - 1]["low"], bars[i - 2]["low"] if i >= 2 else bars[i - 1]["low"])
            else:
                sar = max(sar, bars[i - 1]["high"], bars[i - 2]["high"] if i >= 2 else bars[i - 1]["high"])
            reversed_ = b["low"] < sar if long else b["high"] > sar
            if reversed_:
                long = not long
                sar = ep
                ep = b["high"] if long else b["low"]
                af = start
            elif long and b["high"] > ep:
                ep = b["high"]
                af = min(maximum, af + inc)
            elif not long and b["low"] < ep:
                ep = b["low"]
                af = min(maximum, af + inc)
            values[i] = sar
    return {"lines": [M.line("SAR", values, type="cross")]}


# ---------- VWAP ----------
_BANDS_STDEV = "Standard Deviation"
_BANDS_PERCENT = "Percentage"
_VWAP_BANDS = (
    ("band1", "band1Mult", 1.0, True),
    ("band2", "band2Mult", 2.0, False),
    ("band3", "band3Mult", 3.0, False),
)


def vwap(params, bars):
    anchor = M.ps(params, "anchor", "Session")
    src = M.source_values(bars, M.ps(params, "source", "HLC3"))
    n = len(bars)
    hidden = M.pb(params, "hideDwm", True) and _bar_interval(bars) >= DAY_MS
    values: Series = [None] * n
    bands = [{"mult": max(0.0, M.pf(params, mult, def_mult)),
              "up": [None] * n, "down": [None] * n}
             for show, mult, def_mult, def_on in _VWAP_BANDS
             if M.pb(params, show, def_on)]
    percent_mode = M.ps(params, "bandsMode", _BANDS_STDEV) == _BANDS_PERCENT

    period: Optional[int] = None
    cum_pv = 0.0
    cum_pv2 = 0.0
    cum_v = 0.0
    for i, b in enumerate(bars):
        if hidden:
            break
        key = _period_key(anchor, _time(b))
        if key != period:
            period = key
            cum_pv = cum_pv2 = cum_v = 0.0
        v = b.get("volume")
        if v is not None and M.finite(v) and v > 0:
            tp = src[i]
            cum_pv += tp * v
            cum_pv2 += tp * tp * v
            cum_v += v
        if cum_v <= 0:
            continue
        mean = cum_pv / cum_v
        offset = mean / 100 if percent_mode else math.sqrt(max(0.0, cum_pv2 / cum_v - mean * mean))
        values[i] = mean
        for band in bands:
            band["up"][i] = mean + band["mult"] * offset
            band["down"][i] = mean - band["mult"] * offset

    lines = [M.line("VWAP", values)]
    for i, band in enumerate(bands):
        lines.append(M.line(f"Upper Band #{i + 1}", band["up"]))
        lines.append(M.line(f"Lower Band #{i + 1}", band["down"]))
    return {"lines": lines}


# ---------- Pivot Points ----------
_PIVOT_TRADITIONAL = "Traditional"
_PIVOT_FIBONACCI = "Fibonacci"
_PIVOT_CAMARILLA = "Camarilla"
_PIVOT_WOODIE = "Woodie"
_PIVOT_AUTO = "Auto"


def pivot_points(params, bars):
    interval = _bar_interval(bars)
    requested = M.ps(params, "anchor", _PIVOT_AUTO)
    auto = ("Session" if interval <= 15 * 60000
            else "Week" if interval < DAY_MS
            else "Month" if interval <= DAY_MS
            else "Year")
    anchor = {"Daily": "Session", "Weekly": "Week", "Monthly": "Month", "Yearly": "Year"}.get(requested, auto)
    kind = M.ps(params, "kind", _PIVOT_TRADITIONAL)

    # 每个周期键的 OHLC 聚合（dict 保持首次出现顺序，供 key-1 回查）
    aggs: dict[int, dict] = {}
    for b in bars:
        key = _period_key(anchor, _time(b))
        a = aggs.get(key)
        if a is None:
            aggs[key] = {"open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]}
        else:
            a["high"] = max(a["high"], b["high"])
            a["low"] = min(a["low"], b["low"])
            a["close"] = b["close"]

    n = len(bars)
    levels = {k: [None] * n for k in ("p", "r1", "s1", "r2", "s2", "r3", "s3", "r4", "s4")}
    last_key: Optional[int] = None
    for i, b in enumerate(bars):
        key = _period_key(anchor, _time(b))
        fresh = key != last_key
        last_key = key
        if fresh:
            continue
        prev = aggs.get(key - 1)
        curr = aggs.get(key)
        if prev is None or curr is None:
            continue
        rng = prev["high"] - prev["low"]
        traditional = (prev["high"] + prev["low"] + prev["close"]) / 3
        p = (prev["high"] + prev["low"] + 2 * curr["open"]) / 4 if kind == _PIVOT_WOODIE else traditional
        levels["p"][i] = p
        if kind == _PIVOT_FIBONACCI:
            levels["r1"][i] = traditional + 0.382 * rng
            levels["s1"][i] = traditional - 0.382 * rng
            levels["r2"][i] = traditional + 0.618 * rng
            levels["s2"][i] = traditional - 0.618 * rng
            levels["r3"][i] = traditional + rng
            levels["s3"][i] = traditional - rng
        elif kind == _PIVOT_CAMARILLA:
            cam = 1.1 * rng
            levels["r1"][i] = prev["close"] + cam / 12
            levels["s1"][i] = prev["close"] - cam / 12
            levels["r2"][i] = prev["close"] + cam / 6
            levels["s2"][i] = prev["close"] - cam / 6
            levels["r3"][i] = prev["close"] + cam / 4
            levels["s3"][i] = prev["close"] - cam / 4
            levels["r4"][i] = prev["close"] + cam / 2
            levels["s4"][i] = prev["close"] - cam / 2
        else:
            levels["r1"][i] = 2 * p - prev["low"]
            levels["s1"][i] = 2 * p - prev["high"]
            levels["r2"][i] = p + rng
            levels["s2"][i] = p - rng
            if kind != _PIVOT_WOODIE:
                levels["r3"][i] = prev["high"] + 2 * (p - prev["low"])
                levels["s3"][i] = prev["low"] - 2 * (prev["high"] - p)

    lines = [
        M.line("P", levels["p"]),
        M.line("R1", levels["r1"]),
        M.line("S1", levels["s1"]),
        M.line("R2", levels["r2"]),
        M.line("S2", levels["s2"]),
    ]
    if kind != _PIVOT_WOODIE:
        lines.append(M.line("R3", levels["r3"]))
        lines.append(M.line("S3", levels["s3"]))
    if kind == _PIVOT_CAMARILLA:
        lines.append(M.line("R4", levels["r4"]))
        lines.append(M.line("S4", levels["s4"]))
    return {"lines": lines}


# ---------- 52 Week High/Low ----------
def high_low_52_week(params, bars):
    span = M.pf(params, "weeks", 52) * 7 * DAY_MS
    n = len(bars)
    hi: Series = [None] * n
    lo: Series = [None] * n
    ath: Series = [None] * n
    atl: Series = [None] * n
    max_idx: deque[int] = deque()
    min_idx: deque[int] = deque()
    start = 0
    run_high = -math.inf
    run_low = math.inf
    for i, b in enumerate(bars):
        while max_idx and bars[max_idx[-1]]["high"] <= b["high"]:
            max_idx.pop()
        max_idx.append(i)
        while min_idx and bars[min_idx[-1]]["low"] >= b["low"]:
            min_idx.pop()
        min_idx.append(i)
        while _time(bars[start]) < _time(b) - span:
            start += 1
        while max_idx[0] < start:
            max_idx.popleft()
        while min_idx[0] < start:
            min_idx.popleft()
        hi[i] = bars[max_idx[0]]["high"]
        lo[i] = bars[min_idx[0]]["low"]
        run_high = max(run_high, b["high"])
        run_low = min(run_low, b["low"])
        ath[i] = run_high
        atl[i] = run_low

    lines = [M.line("52 Week High", hi, type="step"), M.line("52 Week Low", lo, type="step")]
    if M.pb(params, "showAllTime", False):
        lines.append(M.line("All-Time High", ath, type="step"))
        lines.append(M.line("All-Time Low", atl, type="step"))
    return {"lines": lines}


# ---------- ZigZag ----------
def zigzag(params, bars):
    dev = M.pf(params, "deviation", 5) / 100
    depth = M.pf(params, "depth", 10)
    pivots: list[dict] = []
    if len(bars) > 1:
        up = bars[1]["close"] >= bars[0]["close"]
        ext = {"i": 0, "price": bars[0]["high"] if up else bars[0]["low"]}
        for i in range(1, len(bars)):
            b = bars[i]
            if up:
                if b["high"] >= ext["price"]:
                    ext = {"i": i, "price": b["high"]}
                elif (b["low"] <= ext["price"] * (1 - dev)
                      and ext["i"] - (pivots[-1]["i"] if pivots else -depth) >= depth):
                    pivots.append(ext)
                    up = False
                    ext = {"i": i, "price": b["low"]}
            elif b["low"] <= ext["price"]:
                ext = {"i": i, "price": b["low"]}
            elif (b["high"] >= ext["price"] * (1 + dev)
                  and ext["i"] - (pivots[-1]["i"] if pivots else -depth) >= depth):
                pivots.append(ext)
                up = True
                ext = {"i": i, "price": b["high"]}
        pivots.append(ext)

    polylines = []
    for k in range(1, len(pivots)):
        a, b = pivots[k - 1], pivots[k]
        polylines.append({
            "key": f"leg{k}",
            "points": [
                {"x": _time(bars[a["i"]]), "price": a["price"]},
                {"x": _time(bars[b["i"]]), "price": b["price"]},
            ],
        })
    return {"lines": [], "polylines": polylines}


# ---------- Williams Fractal ----------
def williams_fractal(params, bars):
    periods = int(M.pf(params, "periods", 2))
    markers = []
    for i in range(periods, len(bars) - periods):
        high = bars[i]["high"]
        low = bars[i]["low"]
        is_up = all(high > bars[k]["high"] for k in range(i - periods, i + periods + 1) if k != i)
        is_down = all(low < bars[k]["low"] for k in range(i - periods, i + periods + 1) if k != i)
        if is_up:
            markers.append({"time": _time(bars[i]), "position": "aboveBar", "shape": "triangleup"})
        if is_down:
            markers.append({"time": _time(bars[i]), "position": "belowBar", "shape": "triangledown"})
    return {"lines": [], "markers": markers}


STUDIES = {
    "parabolic-sar": parabolic_sar,
    "vwap": vwap,
    "pivot-points": pivot_points,
    "52-week-high-low": high_low_52_week,
    "zigzag": zigzag,
    "williams-fractal": williams_fractal,
}
