"""
示例指标脚本：计算 SMA (简单移动平均)
"""

NAME = "SMA"
DESC = "简单移动平均线"
PARAMS = {"period": 20}


def main(params: dict, ohlcv: list) -> list:
    """
    计算 SMA
    返回: [null, ..., sma_value, ...]（warmup 用 None）
    """
    period = int(params.get("period", 20))

    if not ohlcv:
        return []

    closes = [bar["close"] for bar in ohlcv]
    result = [None] * len(closes)

    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1: i + 1]
        result[i] = round(sum(window) / period, 2)

    return result
