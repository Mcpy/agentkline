"""振荡器族（Vela `src/core/native-indicators/classics/oscillators.ts`，
0.8.4 基础批 + 0.10.19 新增批）。

逐条移植 Vela 的 JS 实现：保留其递归种子（SMA seed）、NaN 重置窗口、
`Math.trunc` 取整、零除守卫等语义，不做四舍五入。

缺失值一律为 None（对应 JS NaN）；只输出 golden 中「可见」的 plot
（anchor、全透明辅助线不输出）。0.8.4 基础批不产出 `levels`；
0.10.19 新增批按 descriptor 原样产出 `levels`（与 trend/volume 模块
同一约定，compare.py 在提供时比对）。颜色承载不可由数值推导的语义时
（ASI swing 突破、chop-zone 分级）随 line 输出 `colors`（与 averages
0.10.19 批 Crosses 同一约定）；其余逐 bar 着色与渐变填充带（bands）
属前端视觉规格，不产出。
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


# ---------- 0.10.19 新增：局部原语 ----------

# Vela 经典配色常量（vela.global.js：BULLISH/BEARISH/NEUTRAL/WARNING）
_BULLISH = "#089981"
_BEARISH = "#f23645"
_NEUTRAL = "#787b86"
_WARNING = "#ff9800"


def _channels(hex_color):
    """JS channels：取 #rrggbb 前三字节；不合法返回 None。"""
    s = str(hex_color).strip()
    if len(s) >= 7 and s[0] == "#":
        body = s[1:7]
        if all(c in "0123456789abcdefABCDEF" for c in body):
            return tuple(int(body[i:i + 2], 16) for i in (0, 2, 4))
    return None


def _gradient(value, low, high, from_hex, to_hex):
    """Vela gradient：RGB 线性插值；Math.round 用 floor(x+0.5) 对齐。"""
    a, b = _channels(from_hex), _channels(to_hex)
    if a is None or b is None or not (M.finite(value) and M.finite(low) and M.finite(high)):
        return from_hex
    span = high - low
    t = 0 if span == 0 else max(0.0, min(1.0, (value - low) / span))
    return "#" + "".join(f"{math.floor(a[k] + (b[k] - a[k]) * t + 0.5):02x}" for k in range(3))


def _swing_breakout_colors(values, length, bull, bear, neutral):
    """Vela swingBreakoutColors：ASI 相对最近确认 swing 高/低的突破着色。

    第 i 根确认 candidate = i-length 处的枢轴：左侧 [candidate-length, candidate)
    全部 <= 枢轴（swing high）或 >= 枢轴（swing low），右侧 (candidate, i]
    严格 <（high）或 >（low）；窗口内任何缺失值使两种确认都失败。
    确认后 swingHigh/swingLow 沿用至下次确认；x 高于 swingHigh 着牛色、
    低于 swingLow 着熊色，其余中性（未确认时 NaN 比较恒 false → 中性）。
    """
    swing_high = None
    swing_low = None
    out = []
    for i, x in enumerate(values):
        candidate = i - length
        if candidate - length >= 0:
            pivot = values[candidate]
            is_high = M.finite(pivot)
            is_low = is_high
            k = candidate - length
            while k <= i and (is_high or is_low):
                if k != candidate:
                    v = values[k]
                    if not M.finite(v) or (v > pivot if k < candidate else v >= pivot):
                        is_high = False
                    if not M.finite(v) or (v < pivot if k < candidate else v <= pivot):
                        is_low = False
                k += 1
            if is_high:
                swing_high = pivot
            if is_low:
                swing_low = pivot
        if not M.finite(x):
            out.append(None)
        elif swing_high is not None and x > swing_high:
            out.append(bull)
        elif swing_low is not None and x < swing_low:
            out.append(bear)
        else:
            out.append(neutral)
    return out


def _cumsum(values):
    """JS cumSum：只累加有效值；首个有效值之前为 None，之后遇缺口沿用累计值。"""
    out = [None] * len(values)
    acc = 0.0
    seen = False
    for i, x in enumerate(values):
        if M.finite(x):
            acc += x
            seen = True
        if seen:
            out[i] = acc
    return out


def _rank_correlation(v, n):
    """Vela rankCorrelation：窗口内价格秩与时间秩的 Spearman 秩相关。

    价格降序排名（最高 = 1），并列值取平均秩；时间秩最新 = 1（len - k）。
    RCI = 1 - 6 * Σd² / (n * (n² - 1))，d 为两秩之差。
    """
    out = [None] * len(v)
    if n < 2:
        return out
    scale = 6 / (n * (n * n - 1))

    def fold(f, t):
        w = v[f:t + 1]
        order = sorted(range(n), key=lambda k: -w[k])
        rank = [0.0] * n
        k = 0
        while k < n:
            end = k
            while end + 1 < n and w[order[end + 1]] == w[order[k]]:
                end += 1
            shared = (k + end) / 2 + 1
            for j in range(k, end + 1):
                rank[order[j]] = shared
            k = end + 1
        squares = 0.0
        for k in range(n):
            d = n - k - rank[k]
            squares += d * d
        return 1 - scale * squares

    return M.windowed(v, n, fold)


def _correlation(a, b, n):
    """Vela correlation：n 窗口 Pearson 相关；窗口缺值则缺失，分母为 0 记 0。"""
    out = [None] * len(a)
    if n <= 0:
        return out
    for i in range(n - 1, len(a)):
        f = i - n + 1
        sa = sb = 0.0
        ok = True
        for k in range(f, i + 1):
            x, y = a[k], b[k]
            if not (M.finite(x) and M.finite(y)):
                ok = False
                break
            sa += x
            sb += y
        if not ok:
            continue
        ma, mb = sa / n, sb / n
        cov = va = vb = 0.0
        for k in range(f, i + 1):
            da, db = a[k] - ma, b[k] - mb
            cov += da * db
            va += da * da
            vb += db * db
        denom = math.sqrt(va * vb)
        out[i] = 0 if denom == 0 else cov / denom
    return out


# ---------- 0.10.19 新增：研究 ----------


def accelerator_oscillator(params, bars):
    """Vela accelerator：AC = AO - SMA(AO, 5)，AO = SMA(HL2,5) - SMA(HL2,34)。"""
    hl2 = M.source_values(bars, "HL2")
    ao = M.sub(M.sma(hl2, 5), M.sma(hl2, 34))
    ac = M.sub(ao, M.sma(ao, 5))
    return {"lines": [M.line("AC", ac)],
            "levels": [{"key": "zero", "price": 0, "lineStyle": "dashed", "title": "Zero Line"}]}


def momentum(params, bars):
    """Vela momentum：source 与其 length 根前值之差（绝对差，非百分比）。"""
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    values = M.change(src, M.pi(params, "length", 10))
    return {"lines": [M.line("Momentum", values)],
            "levels": [{"key": "zero", "price": 0, "lineStyle": "dashed", "title": "Zero Line"}]}


def accumulative_swing_index(params, bars):
    """Vela accumulativeSwingIndex：Wilder SI 的逐 bar 累计（cumSum）。

    limitMove 是缩放除数（下限 0.1），不是截断；swingLength 只参与
    swing 突破着色（_swing_breakout_colors）的确认逻辑，不影响 ASI 数值。
    """
    limit = max(M.pf(params, "limitMove", 10), 0.1)
    swing = [None] * len(bars)
    for i in range(1, len(bars)):
        b, p = bars[i], bars[i - 1]
        to_high = abs(b["high"] - p["close"])
        to_low = abs(b["low"] - p["close"])
        rng = b["high"] - b["low"]
        prev_body = abs(p["close"] - p["open"])
        if to_high >= to_low and to_high >= rng:
            r = to_high - 0.5 * to_low + 0.25 * prev_body
        elif to_low >= to_high and to_low >= rng:
            r = to_low - 0.5 * to_high + 0.25 * prev_body
        else:
            r = rng + 0.25 * prev_body
        weighted = (b["close"] - p["close"] + 0.5 * (b["close"] - b["open"])
                    + 0.25 * (p["close"] - p["open"]))
        swing[i] = 0 if r == 0 else 50 * weighted * (max(to_high, to_low) / limit) / r
    values = _cumsum(swing)
    colors = _swing_breakout_colors(values, math.trunc(M.pf(params, "swingLength", 10)),
                                    M.ps(params, "bullColor", _BULLISH),
                                    M.ps(params, "bearColor", _BEARISH),
                                    M.ps(params, "color", _NEUTRAL))
    return {"lines": [M.line("ASI", values, color=M.ps(params, "color", _NEUTRAL), colors=colors)]}


def rank_correlation_index(params, bars):
    """Vela rankCorrelationIndex：价格与时间的秩相关，值域 [-1, 1]。"""
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    values = _rank_correlation(src, M.pi(params, "length", 12))
    ob = M.pf(params, "overbought", 0.8)
    os_ = M.pf(params, "oversold", -0.8)
    return {"lines": [M.line("RCI", values)],
            "levels": [
                {"key": "overbought", "price": ob, "lineStyle": "dashed", "title": "Overbought"},
                {"key": "midline", "price": 0, "lineStyle": "dotted", "title": "Midline"},
                {"key": "oversold", "price": os_, "lineStyle": "dashed", "title": "Oversold"},
            ]}


def majority_rule(params, bars):
    """Vela majorityRule：窗口内收盘高于前一根收盘的 bar 占比（%）。

    首根 change 为 NaN 且 map 传播 NaN，故窗口从第 length+1 根才齐全。
    """
    n = M.pi(params, "length", 14)
    closed_higher = M.mapv(M.change(M.closes(bars)), lambda d: 1 if d > 0 else 0)
    values = M.mapv(M.sumv(closed_higher, n), lambda count: 100 * count / n)
    return {"lines": [M.line("Majority Rule", values)],
            "levels": [{"key": "zero", "price": 50, "lineStyle": "dashed", "title": "Midline"}]}


def advance_decline(params, bars):
    """Vela advanceDecline：窗口内 close>open 数 / close<open 数。

    平盘 bar（close == open）两边都不计；窗口无下跌 bar 时直接读
    上涨 bar 数（JS 注释：never a division by zero）。
    """
    n = M.pi(params, "length", 10)
    up = M.sumv([1 if b["close"] > b["open"] else 0 for b in bars], n)
    down = M.sumv([1 if b["close"] < b["open"] else 0 for b in bars], n)
    values = M.zipv(up, down, lambda u, d: u if d == 0 else u / d)
    return {"lines": [M.line("Advance/Decline", values)],
            "levels": [{"key": "zero", "price": 1, "lineStyle": "dashed", "title": "Even"}]}


def trend_strength_index(params, bars):
    """Vela trendStrength：source 与 bar 序号的 Pearson 相关（非回归斜率）。

    +1 直线上涨、-1 直线下跌、0 无趋势；窗口内价格恒定时分母为 0 记 0。
    """
    src = M.source_values(bars, M.ps(params, "source", "Close"))
    values = _correlation(src, [float(i) for i in range(len(bars))],
                          M.pi(params, "length", 14))
    return {"lines": [M.line("Trend Strength", values)],
            "levels": [{"key": "zero", "price": 0, "lineStyle": "dashed", "title": "Zero Line"}]}


# chop-zone 固定参数（Vela 0.10.19 无输入项）
_CHOP_TREND_LENGTH = 34
_CHOP_RANGE_LENGTH = 30
_CHOP_SPAN = 25
# 分级阈值：|角度| 每越过一档 zone +1（0..4），符号随 rise
_CHOP_ZONE_EDGES = (0.71, 2.14, 3.57, 5)


def _chop_zone(angle):
    """Vela chopZone：按 |angle| 越过阈值档数分级，符号随 angle。"""
    zone = sum(1 for edge in _CHOP_ZONE_EDGES if abs(angle) >= edge)
    return -zone if angle < 0 else zone


def chop_zone(params, bars):
    """Vela chopZone：EMA34 趋势 + 30 根 highest(highs)/lowest(highs) 区间。

    注意 bottom 是「最高价的最低值」而非 lowest(lows)。有效 bar 的值恒为 1，
    信息在逐 bar 颜色：rise → round(atan(|rise|)·180/π) → 分级（0..±4），
    zone 0 着 flat 色，其余按 |zone|/4 从 flat 向 bull/bear 渐变。
    0.10.19 本源不输出 bands/levels（golden 亦无）。
    """
    bull = M.ps(params, "bullColor", _BULLISH)
    bear = M.ps(params, "bearColor", _BEARISH)
    flat = M.ps(params, "flatColor", _WARNING)
    trend = M.ema(M.closes(bars), _CHOP_TREND_LENGTH)
    top = M.highest(M.highs(bars), _CHOP_RANGE_LENGTH)
    bottom = M.lowest(M.highs(bars), _CHOP_RANGE_LENGTH)
    values = [None] * len(bars)
    colors = [None] * len(bars)
    for i in range(1, len(bars)):
        now, before = trend[i], trend[i - 1]
        high, low = top[i], bottom[i]
        if not (M.finite(now) and M.finite(before) and M.finite(high) and M.finite(low)):
            continue
        b = bars[i]
        typical = (b["high"] + b["low"] + b["close"]) / 3
        rng = high - low
        rise = ((now - before) / typical * (_CHOP_SPAN / rng * low)
                if rng > 0 and typical != 0 else 0)
        # JS Math.round 半值向上；此处参数恒非负，floor(x+0.5) 等价
        degrees = math.floor(math.atan(abs(rise)) * 180 / math.pi + 0.5)
        zone = _chop_zone(-degrees if rise < 0 else degrees)
        values[i] = 1
        colors[i] = (flat if zone == 0 else
                     _gradient(abs(zone), 0, len(_CHOP_ZONE_EDGES), flat,
                               bull if zone > 0 else bear))
    return {"lines": [M.line("Chop Zone", values, kind="columns", color=flat,
                             colors=colors, base=0)]}


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
    "accelerator-oscillator": accelerator_oscillator,
    "momentum": momentum,
    "accumulative-swing-index": accumulative_swing_index,
    "rank-correlation-index": rank_correlation_index,
    "majority-rule": majority_rule,
    "advance-decline": advance_decline,
    "trend-strength-index": trend_strength_index,
    "chop-zone": chop_zone,
}
