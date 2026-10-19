"""指标计算数学库（v0.5.3 Vela 经典研究移植）。

所有函数逐字对齐 Vela 0.8.4 `src/core/native-indicators/classics/math.ts` 的语义：
- 缺失值 = None（对应 JS NaN）；窗口/递归遇到 None 会重置状态（与 `windowed`/`recursive` 一致）
- 递归型（EMA/RMA）用前 len 个有效值的 SMA 作为种子，从第 len 个值开始输出
- 不做四舍五入（值保真；显示层自理）
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional

Series = list[Optional[float]]


def finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _clean(values) -> Series:
    return [float(v) if finite(v) else None for v in values]


# ---------- 序列构造 ----------
def source_values(bars: list[dict], source: str = "Close") -> Series:
    out: Series = []
    for b in bars:
        o, h, l, c = b["open"], b["high"], b["low"], b["close"]
        if source == "Open":
            v = o
        elif source == "High":
            v = h
        elif source == "Low":
            v = l
        elif source == "HL2":
            v = (h + l) / 2
        elif source == "HLC3":
            v = (h + l + c) / 3
        elif source == "OHLC4":
            v = (o + h + l + c) / 4
        elif source == "HLCC4":
            v = (h + l + c + c) / 4
        else:
            v = c
        out.append(float(v))
    return out


def volumes(bars: list[dict]) -> Series:
    return [float(b["volume"]) if finite(b.get("volume")) else None for b in bars]


def highs(bars: list[dict]) -> Series:
    return _clean(b["high"] for b in bars)


def lows(bars: list[dict]) -> Series:
    return _clean(b["low"] for b in bars)


def closes(bars: list[dict]) -> Series:
    return _clean(b["close"] for b in bars)


def opens(bars: list[dict]) -> Series:
    return _clean(b["open"] for b in bars)


def zipv(a: Series, b: Series, fn: Callable[[float, float], float]) -> Series:
    out: Series = []
    for x, y in zip(a, b):
        out.append(fn(x, y) if finite(x) and finite(y) else None)
    return out


def mapv(a: Series, fn: Callable[[float], float]) -> Series:
    return [fn(x) if finite(x) else None for x in a]


def sub(a: Series, b: Series) -> Series:
    return zipv(a, b, lambda x, y: x - y)


# ---------- 窗口 ----------
def windowed(v: Series, n: int, fold: Callable[[int, int], float]) -> Series:
    """n 个连续有效值才输出；fold(from, to) 在窗口 [from,to] 上计算。"""
    out: Series = [None] * len(v)
    if n <= 0:
        return out
    run = 0
    for i, x in enumerate(v):
        run = run + 1 if finite(x) else 0
        if run >= n:
            out[i] = fold(i - n + 1, i)
    return out


def sma(v: Series, n: int) -> Series:
    return windowed(v, n, lambda f, t: sum(v[f:t + 1]) / n)


def wma(v: Series, n: int) -> Series:
    norm = n * (n + 1) / 2

    def fold(f: int, t: int) -> float:
        return sum(v[k] * (k - f + 1) for k in range(f, t + 1)) / norm

    return windowed(v, n, fold)


def vwma(src: Series, vol: Series, n: int) -> Series:
    pv = zipv(src, vol, lambda p, q: p * q)
    return zipv(sma(pv, n), sma(vol, n), lambda a, b: a / b if b > 0 else None)


def stdev(v: Series, n: int) -> Series:
    def fold(f: int, t: int) -> float:
        mean = sum(v[f:t + 1]) / n
        return math.sqrt(sum((v[k] - mean) ** 2 for k in range(f, t + 1)) / n)

    return windowed(v, n, fold)


def mean_dev(v: Series, n: int) -> Series:
    def fold(f: int, t: int) -> float:
        mean = sum(v[f:t + 1]) / n
        return sum(abs(v[k] - mean) for k in range(f, t + 1)) / n

    return windowed(v, n, fold)


def highest(v: Series, n: int) -> Series:
    return windowed(v, n, lambda f, t: max(v[f:t + 1]))


def lowest(v: Series, n: int) -> Series:
    return windowed(v, n, lambda f, t: min(v[f:t + 1]))


def bars_since_highest(v: Series, n: int) -> Series:
    def fold(f: int, t: int) -> int:
        m, at = -math.inf, t
        for k in range(f, t + 1):
            if v[k] >= m:
                m, at = v[k], k
        return t - at

    return windowed(v, n, fold)


def bars_since_lowest(v: Series, n: int) -> Series:
    def fold(f: int, t: int) -> int:
        m, at = math.inf, t
        for k in range(f, t + 1):
            if v[k] <= m:
                m, at = v[k], k
        return t - at

    return windowed(v, n, fold)


# ---------- 递归 ----------
def recursive(v: Series, n: int, alpha: float) -> Series:
    out: Series = [None] * len(v)
    run = 0
    prev: Optional[float] = None
    for i, x in enumerate(v):
        if not finite(x):
            run, prev = 0, None
            continue
        run += 1
        if prev is not None:
            prev = alpha * x + (1 - alpha) * prev
            out[i] = prev
        elif run >= n:
            prev = sum(v[i - n + 1:i + 1]) / n
            out[i] = prev
    return out


def ema(v: Series, n: int) -> Series:
    return recursive(v, n, 2 / (n + 1))


def rma(v: Series, n: int) -> Series:
    return recursive(v, n, 1 / n)


def change(v: Series, n: int = 1) -> Series:
    out: Series = [None] * len(v)
    for i in range(n, len(v)):
        a, b = v[i], v[i - n]
        if finite(a) and finite(b):
            out[i] = a - b
    return out


def roc(v: Series, n: int) -> Series:
    out: Series = [None] * len(v)
    for i in range(n, len(v)):
        a, b = v[i], v[i - n]
        if finite(a) and finite(b) and b != 0:
            out[i] = 100 * (a - b) / b
    return out


def shift(v: Series, n: int) -> Series:
    out: Series = [None] * len(v)
    for i in range(len(v)):
        j = i - n
        if 0 <= j < len(v):
            out[i] = v[j]
    return out


# ---------- 价格派生 ----------
def true_range(bars: list[dict]) -> Series:
    out: Series = [None] * len(bars)
    for i, b in enumerate(bars):
        if i == 0:
            out[i] = b["high"] - b["low"]
            continue
        pc = bars[i - 1]["close"]
        out[i] = max(b["high"] - b["low"], abs(b["high"] - pc), abs(b["low"] - pc))
    return out


def atr(bars: list[dict], n: int) -> Series:
    return rma(true_range(bars), n)


def rsi_series(v: Series, n: int) -> Series:
    d = change(v)
    up = mapv(d, lambda x: max(x, 0))
    dn = mapv(d, lambda x: max(-x, 0))
    return zipv(rma(up, n), rma(dn, n), lambda u, w: 100 if w == 0 else 100 - 100 / (1 + u / w))


def stoch(v: Series, hi: Series, lo: Series, n: int) -> Series:
    hh, ll = highest(hi, n), lowest(lo, n)
    out: Series = [None] * len(v)
    for i, x in enumerate(v):
        h, l = hh[i], ll[i]
        if not (finite(x) and finite(h) and finite(l)):
            continue
        out[i] = 50 if h == l else 100 * (x - l) / (h - l)
    return out


def linreg(v: Series, n: int, offset: int = 0) -> Series:
    sx = (n - 1) * n / 2
    sxx = (n - 1) * n * (2 * n - 1) / 6
    denom = n * sxx - sx * sx

    def fold(f: int, t: int) -> float:
        sy = sxy = 0.0
        for k in range(f, t + 1):
            x = k - f
            sy += v[k]
            sxy += x * v[k]
        slope = 0 if denom == 0 else (n * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n
        return intercept + slope * (n - 1 - offset)

    return windowed(v, n, fold)


def hma(v: Series, n: int) -> Series:
    m = max(2, int(n))
    raw = sub(mapv(wma(v, max(1, int(m / 2))), lambda x: 2 * x), wma(v, m))
    return wma(raw, max(1, round(math.sqrt(m))))


def alma(v: Series, n: int, offset: float, sigma: float) -> Series:
    m = offset * (n - 1)
    s = n / max(sigma, 1e-9)
    weights = [math.exp(-((i - m) ** 2) / (2 * s * s)) for i in range(n)]
    norm = sum(weights)

    def fold(f: int, t: int) -> float:
        return sum(v[f + i] * weights[i] for i in range(n)) / norm if norm else None

    return windowed(v, n, fold)


def dema(v: Series, n: int) -> Series:
    e1 = ema(v, n)
    return sub(mapv(e1, lambda x: 2 * x), ema(e1, n))


def tema(v: Series, n: int) -> Series:
    e1 = ema(v, n)
    e2 = ema(e1, n)
    e3 = ema(e2, n)
    return zipv(zipv(mapv(e1, lambda x: 3 * x), mapv(e2, lambda x: 3 * x), lambda a, b: a - b), e3, lambda a, b: a + b)


def kama(v: Series, n: int, fast_alpha: float = 2 / 3, slow_alpha: float = 2 / 31) -> Series:
    direction = mapv(change(v, n), abs)
    volatility = sumv(mapv(change(v), abs), n)
    out: Series = [None] * len(v)
    prev: Optional[float] = None
    for i, x in enumerate(v):
        if not finite(x):
            continue
        d, w = direction[i], volatility[i]
        if not (finite(d) and finite(w)):
            prev = prev if prev is not None else x
            out[i] = prev
            continue
        er = 0 if w == 0 else d / w
        sc = (er * (fast_alpha - slow_alpha) + slow_alpha) ** 2
        prev = prev + sc * (x - prev) if prev is not None else x
        out[i] = prev
    return out


def mcginley(v: Series, n: int) -> Series:
    out: Series = [None] * len(v)
    prev: Optional[float] = None
    for i, x in enumerate(v):
        if not finite(x):
            continue
        if prev is None:
            prev = x
        else:
            ratio = 0 if prev == 0 else x / prev
            denom = n * ratio ** 4
            prev = prev + (x - prev) / denom if denom else prev
        out[i] = prev
    return out


def hamming(v: Series, n: int) -> Series:
    """Hamming 窗口加权均线（Vela hamming：权重 i/(n-1)，反向对齐 to-k）。"""
    if n <= 1:
        return list(v)
    weights = [0.54 - 0.46 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]
    norm = sum(weights)

    def fold(f: int, t: int) -> float:
        acc = sum(v[k] * weights[t - k] for k in range(f, t + 1))
        return acc / norm if norm else None

    return windowed(v, n, fold)


MA_TYPES = ["SMA", "EMA", "WMA", "RMA (SMMA)", "HMA", "ALMA", "VWMA", "DEMA", "TEMA", "KAMA", "LSMA", "McGinley", "Hamming"]


def moving_average_of(kind: str, src: Series, bars: list[dict], n: int,
                      alma_offset: float = 0.85, alma_sigma: float = 6, lsma_offset: int = 0) -> Series:
    if kind == "EMA":
        return ema(src, n)
    if kind == "WMA":
        return wma(src, n)
    if kind in ("RMA", "RMA (SMMA)"):
        return rma(src, n)
    if kind == "HMA":
        return hma(src, n)
    if kind == "ALMA":
        return alma(src, n, alma_offset, alma_sigma)
    if kind == "VWMA":
        return vwma(src, volumes(bars), n)
    if kind == "DEMA":
        return dema(src, n)
    if kind == "TEMA":
        return tema(src, n)
    if kind == "KAMA":
        return kama(src, n)
    if kind == "LSMA":
        return linreg(src, n, lsma_offset)
    if kind == "McGinley":
        return mcginley(src, n)
    if kind == "Hamming":
        return hamming(src, n)
    return sma(src, n)


# ---------- 参数 ----------
def p(params: dict, key: str, default):
    v = (params or {}).get(key)
    if v is None:
        return default
    return v


def pi(params: dict, key: str, default: int) -> int:
    v = p(params, key, default)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def pf(params: dict, key: str, default: float) -> float:
    v = p(params, key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def pb(params: dict, key: str, default: bool) -> bool:
    v = p(params, key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "on")
    return bool(v)


def ps(params: dict, key: str, default: str) -> str:
    v = p(params, key, default)
    return str(v)


def line(name: str, values: Series, **extra) -> dict:
    out = {"name": name, "values": values}
    out.update(extra)
    return out


def slope_colors(values: Series, bull: str, bear: str, flat: str) -> list:
    out = []
    for i, x in enumerate(values):
        if not finite(x):
            out.append(None)
            continue
        prev = values[i - 1] if i > 0 else None
        if not finite(prev):
            out.append(flat)
        else:
            out.append(bull if x > prev else bear if x < prev else flat)
    return out


def sumv(v: Series, n: int) -> Series:
    return windowed(v, n, lambda f, t: sum(v[f:t + 1]))


def cmo(v: Series, n: int) -> Series:
    d = change(v)
    up = sumv(mapv(d, lambda x: max(x, 0)), n)
    dn = sumv(mapv(d, lambda x: max(-x, 0)), n)
    return zipv(up, dn, lambda u, w: 0 if u + w == 0 else 100 * (u - w) / (u + w))
