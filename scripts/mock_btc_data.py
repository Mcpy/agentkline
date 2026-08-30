"""
示例数据源脚本：生成模拟 BTC 日线数据
用于测试 AgentKline
"""
import random
from datetime import datetime, timedelta


def main(params: dict) -> list:
    """
    生成模拟 K 线数据
    params:
        days: 生成天数 (默认 365)
        start_price: 起始价格 (默认 30000)
        symbol: 交易对名称 (默认 BTCUSDT)
    """
    days = params.get("days", 365)
    start_price = params.get("start_price", 30000)

    ohlcv = []
    price = start_price
    base_time = datetime.now() - timedelta(days=days)

    for i in range(days):
        # 随机游走
        change_pct = random.gauss(0.001, 0.03)  # 均值 0.1%，标准差 3%
        open_price = price
        close_price = price * (1 + change_pct)
        high_price = max(open_price, close_price) * (1 + abs(random.gauss(0, 0.01)))
        low_price = min(open_price, close_price) * (1 - abs(random.gauss(0, 0.01)))
        volume = random.uniform(1000, 50000)

        # 日线时间戳规范到当天 0 点（避免显示异常时分）
        day = (base_time + timedelta(days=i)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        timestamp = int(day.timestamp() * 1000)

        ohlcv.append({
            "timestamp": timestamp,
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": round(volume, 2)
        })

        price = close_price

    return ohlcv
