"""均线族（Vela averages.ts）。"""
from __future__ import annotations

import math

from . import mathlib as M


def _fixed_average(title: str, smooth):
    def compute(params, bars):
        src = M.source_values(bars, M.ps(params, "source", "Close"))
        values = smooth(src, M.pi(params, "length", 20))
        off = int(M.pf(params, "offset", 0))
        if off:
            values = M.shift(values, off)
        return {"lines": [M.line(title, values)]}

    return compute


def _slope_plot(title: str, values):
    return M.line(title, values)


def sma(params, bars):
    return _fixed_average("SMA", M.sma)(params, bars)


def ema(params, bars):
    return _fixed_average("EMA", M.ema)(params, bars)


def moving_average(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    kind = M.ps(params, "maType", "SMA")
    values = M.moving_average_of(kind, src, bars, M.pi(params, "length", 20),
                                 M.pf(params, "almaOffset", 0.85), M.pf(params, "almaSigma", 6),
                                 M.pi(params, "lsmaOffset", 0))
    off = int(M.pf(params, "offset", 0))
    if off:
        values = M.shift(values, off)
    lines = [M.line(kind, values)]
    if M.pb(params, "showMa2", False):
        src2 = M.source_values(bars, M.ps(params, "ma2Source", "Close"))
        kind2 = M.ps(params, "ma2Type", "SMA")
        v2 = M.moving_average_of(kind2, src2, bars, M.pi(params, "ma2Length", 50),
                                 M.pf(params, "almaOffset", 0.85), M.pf(params, "almaSigma", 6),
                                 M.pi(params, "lsmaOffset", 0))
        if off:
            v2 = M.shift(v2, off)
        lines.append(M.line(f"{kind2} 2", v2))
    return {"lines": lines}


def rma(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    return {"lines": [M.line("RMA", M.rma(src, M.pi(params, "length", 14)))]}


def zlema(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    n = M.pi(params, "length", 21)
    lag = math.floor((n - 1) / 2 + 0.5)
    delagged = M.zipv(src, M.shift(src, lag), lambda a, b: 2 * a - b)
    return {"lines": [M.line("ZLEMA", M.ema(delagged, n))]}


def vidya(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    n = M.pi(params, "length", 12)
    scaler_len = M.pi(params, "scalerLength", 9)
    mode = M.ps(params, "scaler", "Momentum (|CMO|)")
    momentum = M.mapv(M.cmo(src, scaler_len), lambda x: abs(x) / 100)
    short_dev = M.stdev(src, scaler_len)
    ref_dev = M.stdev(src, M.pi(params, "refLength", 30))
    volatility = M.zipv(short_dev, ref_dev, lambda s, r: s / r if r > 0 else 0)
    scale = volatility if mode == "Volatility (StDev Ratio)" else momentum
    alpha_base = 2 / (n + 1)
    out: list = [None] * len(src)
    prev = None
    for i, x in enumerate(src):
        if x is None:
            continue
        k = scale[i]
        if prev is None or k is None:
            prev = x
        else:
            alpha = min(alpha_base * k, 1)
            prev = alpha * x + (1 - alpha) * prev
        out[i] = prev
    return {"lines": [M.line("VIDYA", out)]}


def ma_envelope(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    basis = M.moving_average_of(M.ps(params, "maType", "SMA"), src, bars, M.pi(params, "length", 20))
    k = M.pf(params, "percent", 2.5) / 100
    upper = M.mapv(basis, lambda x: x * (1 + k))
    lower = M.mapv(basis, lambda x: x * (1 - k))
    return {"lines": [M.line("Basis", basis), M.line("Upper", upper), M.line("Lower", lower)]}


def linear_regression(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    n = M.pi(params, "length", 100)
    curve = M.linreg(src, n, 0)
    if M.ps(params, "mode", "Curve") == "Slope":
        slope = M.zipv(curve, M.linreg(src, n, 1), lambda a, b: a - b)
        return {"lines": [M.line("Slope", slope)]}
    return {"lines": [M.line("Curve", curve)]}


STUDIES = {
    "sma": sma,
    "ema": ema,
    "moving-average": moving_average,
    "rma": rma,
    "zlema": zlema,
    "vidya": vidya,
    "ma-envelope": ma_envelope,
    "linear-regression": linear_regression,
}
