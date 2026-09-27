"""
内置指标：EMA 指数均线组（v0.4.3 新增，三线制同 MA）
"""

NAME = "EMA"
DESC = "指数移动平均线组（默认 EMA5/EMA10/EMA20 三线）"
PARAMS = {"periods": [5, 10, 20]}

_COLORS = ["#ffb300", "#29b6f6", "#ce93d8", "#ef5350", "#26a69a", "#ff8a65"]


def main(params: dict, ohlcv: list) -> dict:
    periods = params.get("periods") or [5, 10, 20]
    if isinstance(periods, int):
        periods = [periods]
    if not ohlcv:
        return {"lines": []}
    closes = [bar["close"] for bar in ohlcv]
    lines = []
    for idx, p in enumerate(periods):
        p = int(p)
        k = 2.0 / (p + 1)
        vals = [None] * len(closes)
        ema = None
        for i, c in enumerate(closes):
            ema = c if ema is None else c * k + ema * (1 - k)
            if i >= p - 1:
                vals[i] = round(ema, 2)
        lines.append({"name": f"EMA{p}", "type": "line", "values": vals,
                      "style": {"color": _COLORS[idx % len(_COLORS)], "lineWidth": 1}})
    return {"lines": lines}
