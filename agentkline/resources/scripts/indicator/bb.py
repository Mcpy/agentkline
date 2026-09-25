"""
指标脚本：布林带 Bollinger Bands (多线: 上轨/中轨/下轨)
返回 lines 结构，画在主图
"""

NAME = "BOLL"
DESC = "布林带：上轨/中轨/下轨"
PARAMS = {"period": 20, "std": 2}


def main(params: dict, ohlcv: list) -> dict:
    period = int(params.get("period", 20))
    std_mult = float(params.get("std", 2))

    if not ohlcv:
        return {"lines": []}

    closes = [bar["close"] for bar in ohlcv]
    n = len(closes)
    upper = [None] * n
    mid = [None] * n
    lower = [None] * n

    for i in range(period - 1, n):
        window = closes[i - period + 1: i + 1]
        mean = sum(window) / period
        var = sum((x - mean) ** 2 for x in window) / period
        std = var ** 0.5
        mid[i] = round(mean, 2)
        upper[i] = round(mean + std_mult * std, 2)
        lower[i] = round(mean - std_mult * std, 2)

    return {
        "lines": [
            {"name": "BB_UPPER", "type": "line", "values": upper,
             "style": {"color": "#ffa726", "lineWidth": 1}},
            {"name": "BB_MID", "type": "line", "values": mid,
             "style": {"color": "#4fc3f7", "lineWidth": 1}},
            {"name": "BB_LOWER", "type": "line", "values": lower,
             "style": {"color": "#ffa726", "lineWidth": 1}},
        ]
    }
