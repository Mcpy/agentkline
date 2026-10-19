"""
内置指标：MA 均线组（v0.4.3 三线制，传统面板语义：一个实例一组线）
"""

# 只出计算值：类型/颜色/线宽/填充带/圆点等视觉由前端中间层 visual_spec.js 统一决定（脚本纯值化）。
NAME = "MA"
DESC = "移动平均线组（默认 MA5/MA10/MA20 三线）"
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
        vals = [None] * len(closes)
        for i in range(p - 1, len(closes)):
            vals[i] = round(sum(closes[i - p + 1: i + 1]) / p, 2)
        lines.append({"name": f"MA{p}", "values": vals})
    return {"lines": lines}
