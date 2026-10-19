"""趋势研究族（Vela 0.8.4 `classics/trend.ts`）：Aroon / ADX / Vortex。"""
from __future__ import annotations

from . import mathlib as M


def aroon(params, bars):
    n = M.pi(params, "length", 14)
    if n <= 0:
        empty = [None] * len(bars)
        return {"lines": [M.line("Aroon Up", empty), M.line("Aroon Down", empty)]}
    up = M.mapv(M.bars_since_highest(M.highs(bars), n), lambda x: 100 * (n - x) / n)
    down = M.mapv(M.bars_since_lowest(M.lows(bars), n), lambda x: 100 * (n - x) / n)
    return {"lines": [M.line("Aroon Up", up), M.line("Aroon Down", down)]}


def average_directional_index(params, bars):
    di_len = M.pi(params, "diLength", 14)
    adx_len = M.pi(params, "adxLength", 14)
    n = len(bars)

    # 方向运动：首根无前值，保持缺失；其余按 Wilder 规则二选一。
    plus_dm: M.Series = [None] * n
    minus_dm: M.Series = [None] * n
    for i in range(1, n):
        up = bars[i]["high"] - bars[i - 1]["high"]
        dn = bars[i - 1]["low"] - bars[i]["low"]
        plus_dm[i] = up if up > dn and up > 0 else 0
        minus_dm[i] = dn if dn > up and dn > 0 else 0

    atr_line = M.rma(M.true_range(bars), di_len)
    plus_di = M.zipv(M.rma(plus_dm, di_len), atr_line, lambda d, a: 0 if a == 0 else 100 * d / a)
    minus_di = M.zipv(M.rma(minus_dm, di_len), atr_line, lambda d, a: 0 if a == 0 else 100 * d / a)
    dx = M.zipv(plus_di, minus_di, lambda p, m: 0 if p + m == 0 else 100 * abs(p - m) / (p + m))
    adx_line = M.rma(dx, adx_len)
    key_level = M.pf(params, "keyLevel", 25)
    return {
        "lines": [
            M.line("+DI", plus_di),
            M.line("-DI", minus_di),
            M.line("ADX", adx_line),
        ],
        "levels": [{"key": "keyLevel", "price": key_level, "lineStyle": "dashed", "title": "Key Level"}],
    }


def vortex_indicator(params, bars):
    n = M.pi(params, "length", 14)
    m = len(bars)

    vm_plus: M.Series = [None] * m
    vm_minus: M.Series = [None] * m
    for i in range(1, m):
        vm_plus[i] = abs(bars[i]["high"] - bars[i - 1]["low"])
        vm_minus[i] = abs(bars[i]["low"] - bars[i - 1]["high"])

    tr_sum = M.sumv(M.true_range(bars), n)
    vi_plus = M.zipv(M.sumv(vm_plus, n), tr_sum, lambda v, t: None if t == 0 else v / t)
    vi_minus = M.zipv(M.sumv(vm_minus, n), tr_sum, lambda v, t: None if t == 0 else v / t)
    return {
        "lines": [M.line("VI+", vi_plus), M.line("VI-", vi_minus)],
        "levels": [{"key": "baseline", "price": 1, "lineStyle": "dotted", "title": "Baseline"}],
    }


STUDIES = {
    "aroon": aroon,
    "average-directional-index": average_directional_index,
    "vortex-indicator": vortex_indicator,
}
