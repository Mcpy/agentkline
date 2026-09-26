"""
示例数据源：确定性随机游走合成 K 线（离线可回溯）
- 可重放：同 (symbol, 日期) 永远同值——种子绑绝对日序号，与查询窗口无关
- 连续：价格自创世点累积，跨窗口衔接无跳变
- 有界：历史止于创世点 GENESIS，回溯到顶返回空（backfill 自然终止）
"""
import random
from datetime import datetime

NAME = "模拟行情 (mock)"
DESC = "确定性随机游走合成K线：可重放/跨窗连续/历史止于2020-01-01创世点"
PARAMS = {"symbol": "BTC/USDT", "days": 365, "start_price": 30000}
CAPS = {"backfill": True, "symbols": False, "ticker": True}
IDENTITY = ["symbol"]
INTERVALS = ["1d", "1w"]  # 合成日线/周线两档（周线=日线聚合语义简化：同序列换标签）

DAY_MS = 86_400_000
GENESIS_TS = int(datetime(2020, 1, 1).timestamp() * 1000)
GENESIS_IDX = GENESIS_TS // DAY_MS


def _day_rng(symbol: str, day_idx: int) -> random.Random:
    """逐日确定性种子：与查询窗口无关"""
    return random.Random(f"{symbol}#{day_idx}")


def main(params: dict, until=None) -> list:
    """
    params: symbol / days(首屏窗口) / start_price(创世价) / limit(回溯窗口，系统注入)
    until: 毫秒时间戳，返回该时间之前的K线（回溯）
    """
    symbol = params.get("symbol", "BTC/USDT")
    start_price = float(params.get("start_price", 30000))

    import time
    end_ts = int(until) if until else int(time.time() * 1000)
    end_idx = end_ts // DAY_MS
    if until:
        n = int(params.get("limit") or 200)
    else:
        n = int(params.get("days") or 365)
    if end_idx <= GENESIS_IDX:
        return []  # 回溯到顶：历史有界
    start_idx = max(GENESIS_IDX, end_idx - n)

    # 自创世累积价格（保证跨窗口连续 + 可重放）
    price = start_price
    bars = []
    for idx in range(GENESIS_IDX, end_idx):
        rng = _day_rng(symbol, idx)
        change = rng.gauss(0.001, 0.03)
        open_p = price
        close_p = price * (1 + change)
        high_p = max(open_p, close_p) * (1 + abs(rng.gauss(0, 0.01)))
        low_p = min(open_p, close_p) * (1 - abs(rng.gauss(0, 0.01)))
        vol = rng.uniform(1000, 50000)
        if idx >= start_idx:
            bars.append({
                "timestamp": idx * DAY_MS,
                "open": round(open_p, 2),
                "high": round(high_p, 2),
                "low": round(low_p, 2),
                "close": round(close_p, 2),
                "volume": round(vol, 2),
            })
        price = close_p
    return bars


def ticker(params: dict) -> dict:
    """合成报价：按 symbol 种子 + 小时正弦波心跳（e2e/演示/雷达面板用）"""
    import time, math, hashlib
    sym = params.get("symbol", "BTC/USDT")
    seed = int(hashlib.md5(sym.encode()).hexdigest()[:8], 16)
    base = float(params.get("start_price", 30000)) + (seed % 10000)
    ts = int(time.time() * 1000)
    phase = ts / 3_600_000 + seed % 100
    return {"price": round(base * (1 + 0.05 * math.sin(phase)), 2), "ts": ts,
            "change_pct": round(5 * math.cos(phase), 2)}


def tickers(params_list: list) -> list:
    """批量合成报价（性能② e2e/演示用）"""
    return [ticker(p) for p in params_list]
