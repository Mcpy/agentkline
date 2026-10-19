"""
内置指标：EMA 指数均线组（v0.4.3 新增，三线制同 MA）
"""

# 只出计算值：类型/颜色/线宽/填充带/圆点等视觉由前端中间层 visual_spec.js 统一决定（脚本纯值化）。
NAME = "EMA"
DESC = "指数移动平均线组（默认 EMA5/EMA10/EMA20 三线）"
PARAMS = {"periods": [5, 10, 20]}



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
        lines.append({"name": f"EMA{p}", "values": vals})
    return {"lines": lines}
