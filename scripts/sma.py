"""
示例指标脚本：计算 SMA (简单移动平均)
用于测试 AgentKline 指标功能
"""

# 参数默认值（用于自动命名 SMA(20) 与设置弹窗回显）
PARAMS = {"period": 20}


def main(params: dict, ohlcv: list) -> list:
    """
    计算 SMA
    params:
        period: 均线周期 (默认 20)
    ohlcv: K线数据 [{timestamp, open, high, low, close, volume}, ...]
    返回: [null, null, ..., sma_value, sma_value, ...]
    """
    period = params.get("period", 20)

    if not ohlcv:
        return []

    closes = [bar["close"] for bar in ohlcv]
    result = [None] * len(closes)

    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1: i + 1]
        result[i] = round(sum(window) / period, 2)

    return result
