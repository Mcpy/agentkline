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
    """0.8.4 兼容：旧 type=linear-regression（Curve/Slope）。新目录改用 lsma + slope。"""
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    n = M.pi(params, "length", 100)
    curve = M.linreg(src, n, 0)
    if M.ps(params, "mode", "Curve") == "Slope":
        slope = M.zipv(curve, M.linreg(src, n, 1), lambda a, b: a - b)
        return {"lines": [M.line("Slope", slope)]}
    return {"lines": [M.line("Curve", curve)]}


def lsma(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    n = M.pi(params, "length", 25)
    off = M.pi(params, "offset", 0)
    return {"lines": [M.line("LSMA", M.linreg(src, n, off))]}


def linear_regression_slope(params, bars):
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    n = M.pi(params, "length", 100)
    slope = M.zipv(M.linreg(src, n, 0), M.linreg(src, n, 1), lambda a, b: a - b)
    return {"lines": [M.line("Slope", slope)],
            "levels": [{"key": "zero", "price": 0, "lineStyle": "dashed", "title": "Zero Line"}]}


# ---------- Vela 0.10.19 新增：交叉 / 多均线 / 价格平均 ----------

# Vela 经典配色常量（vela.global.js：INFO/WARNING/BULLISH/BEARISH）
_INFO = "#5b9cf6"
_WARNING = "#ff9800"
_BULLISH = "#089981"
_BEARISH = "#f23645"


def _cross_directions(a: M.Series, b: M.Series) -> list[int]:
    """Vela crossDirections：逐 bar 比较两线差值的符号翻转。

    now = a[i]-b[i]，before = a[i-1]-b[i-1]；严格穿越（now>0 且 before<0 → 1，
    now<0 且 before>0 → -1），相等/触碰不算交叉。JS 里 NaN 参与比较恒为 false，
    这里 None（warmup 段）同样归 0。首 bar 无前值 → 0。
    """
    out: list[int] = []
    for i in range(len(a)):
        if i == 0 or not (M.finite(a[i]) and M.finite(b[i])
                          and M.finite(a[i - 1]) and M.finite(b[i - 1])):
            out.append(0)
            continue
        now = a[i] - b[i]
        before = a[i - 1] - b[i - 1]
        out.append(1 if now > 0 and before < 0 else -1 if now < 0 and before > 0 else 0)
    return out


def _cross_study(first_key: str, first_title: str, first_length: int, first_smooth,
                 second_key: str, second_title: str, second_length: int, second_smooth):
    """Vela crossStudy 工厂：两条均线 + Crosses 圆点。

    交叉标记归属「观察到符号翻转的那根 bar」（比较 i-1 → i），点值取第一条线
    a[i]（JS 注释：点落在两线交汇处，不用十字glyph）；逐点色牛交叉 bullColor、
    熊交叉 bearColor，非交叉 bar 为 None。
    """
    def compute(params, bars):
        src = M.source_values(bars, M.ps(params, "source", "Close"))
        a = first_smooth(src, M.pi(params, f"{first_key}Length", first_length))
        b = second_smooth(src, M.pi(params, f"{second_key}Length", second_length))
        directions = _cross_directions(a, b)
        bull = M.ps(params, "bullColor", _BULLISH)
        bear = M.ps(params, "bearColor", _BEARISH)
        crosses = [a[i] if d != 0 else None for i, d in enumerate(directions)]
        colors = [None if d == 0 else bull if d > 0 else bear for d in directions]
        return {"lines": [
            M.line(first_title, a, color=M.ps(params, f"{first_key}Color", _INFO), width=2),
            M.line(second_title, b, color=M.ps(params, f"{second_key}Color", _WARNING), width=2),
            M.line("Crosses", crosses, type="circles", color=bull, colors=colors, width=4),
        ]}

    return compute


def ma_cross(params, bars):
    """Vela maCross：SMA 短/长均线交叉。"""
    return _cross_study("short", "Short", 9, M.sma, "long", "Long", 26, M.sma)(params, bars)


def ema_cross(params, bars):
    """Vela emaCross：EMA 短/长均线交叉。"""
    return _cross_study("short", "Short", 9, M.ema, "long", "Long", 26, M.ema)(params, bars)


def ma_with_ema_cross(params, bars):
    """Vela maWithEmaCross：SMA(maLength) 与 EMA(emaLength) 交叉。"""
    return _cross_study("ma", "MA", 10, M.sma, "ema", "EMA", 10, M.ema)(params, bars)


def _line_ink(index: int, count: int) -> str:
    """Vela lineInk = gradient(index, 0, count-1, INFO, WARNING)：RGB 线性插值。"""
    if count <= 1:
        return _INFO
    t = max(0.0, min(1.0, index / (count - 1)))
    a = tuple(int(_INFO[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(_WARNING[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{math.floor(a[k] + (b[k] - a[k]) * t + 0.5):02x}" for k in range(3))


def _multi_average(default_lengths: list[int]):
    """Vela multiAverage 工厂：同一 maType/source 的多条均线。

    线标题为 `${maType} ${length}`（如 "SMA 14"）；默认色按 lineInk 从
    INFO 到 WARNING 渐变。maType 仅 SMA/EMA/WMA（BASIC_MA_TYPES）。
    """
    def compute(params, bars):
        kind = M.ps(params, "maType", "SMA")
        src = M.source_values(bars, M.ps(params, "source", "Close"))
        lines = []
        for i, default in enumerate(default_lengths):
            n = M.pi(params, f"length{i + 1}", default)
            values = M.moving_average_of(kind, src, bars, n)
            lines.append(M.line(f"{kind} {n}", values,
                                color=M.ps(params, f"color{i + 1}", _line_ink(i, len(default_lengths))),
                                width=2))
        return {"lines": lines}

    return compute


def moving_average_double(params, bars):
    """Vela maDouble：双均线（默认 14/21）。"""
    return _multi_average([14, 21])(params, bars)


def moving_average_triple(params, bars):
    """Vela maTriple：三均线（默认 14/21/35）。"""
    return _multi_average([14, 21, 35])(params, bars)


def moving_average_multiple(params, bars):
    """Vela maMultiple：六均线（默认 14/21/35/50/100/200）。"""
    return _multi_average([14, 21, 35, 50, 100, 200])(params, bars)


# Vela GUPPY_LINES：trader 组（短周期）与 investor 组（长周期），各 6 条 EMA
_GUPPY_LINES = (
    ("trader1", 3, True), ("trader2", 5, True), ("trader3", 8, True),
    ("trader4", 10, True), ("trader5", 12, True), ("trader6", 15, True),
    ("investor1", 30, False), ("investor2", 35, False), ("investor3", 40, False),
    ("investor4", 45, False), ("investor5", 50, False), ("investor6", 60, False),
)


def guppy_multiple_moving_average(params, bars):
    """Vela guppy（GMMA）：12 条 EMA，标题 `EMA ${len}`。

    颜色按分组：trader 组共用 traderColor（默认 INFO），investor 组共用
    investorColor（默认 WARNING）；线宽 1。EMA 用前 len 个值 SMA 种子（M.ema）。
    """
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    trader_ink = M.ps(params, "traderColor", _INFO)
    investor_ink = M.ps(params, "investorColor", _WARNING)
    lines = []
    for key, default, trader in _GUPPY_LINES:
        n = M.pi(params, key, default)
        lines.append(M.line(f"EMA {n}", M.ema(src, n),
                            color=trader_ink if trader else investor_ink, width=1))
    return {"lines": lines}


# ---------- 价格平均（Vela priceStudy，无周期参数，逐 bar 全长输出） ----------
# 属价格派生而非平滑均线，按任务约定归入本文件。

def median_price(params, bars):
    """Vela medianPrice：HL2 = (high+low)/2。"""
    return {"lines": [M.line("Median Price", M.source_values(bars, "HL2"),
                             color=M.ps(params, "color", _INFO))]}


def typical_price(params, bars):
    """Vela typicalPrice：HLC3 = (high+low+close)/3。"""
    return {"lines": [M.line("Typical Price", M.source_values(bars, "HLC3"),
                             color=M.ps(params, "color", _INFO))]}


def average_price(params, bars):
    """Vela averagePrice：OHLC4 = (open+high+low+close)/4。"""
    return {"lines": [M.line("Average Price", M.source_values(bars, "OHLC4"),
                             color=M.ps(params, "color", _INFO))]}


STUDIES = {
    "sma": sma,
    "ema": ema,
    "moving-average": moving_average,
    "rma": rma,
    "zlema": zlema,
    "vidya": vidya,
    "ma-envelope": ma_envelope,
    "linear-regression": linear_regression,
    "lsma": lsma,
    "linear-regression-slope": linear_regression_slope,
    "ma-cross": ma_cross,
    "ema-cross": ema_cross,
    "ma-with-ema-cross": ma_with_ema_cross,
    "moving-average-double": moving_average_double,
    "moving-average-triple": moving_average_triple,
    "moving-average-multiple": moving_average_multiple,
    "guppy-multiple-moving-average": guppy_multiple_moving_average,
    "median-price": median_price,
    "typical-price": typical_price,
    "average-price": average_price,
}
