"""
数据源脚本：ccxt 接入 Binance BTC 永续合约（合约）实时数据
用于 AgentKline 数据源（支持轮询 + 历史回溯）
含重试逻辑（Binance 有间歇性 WAF 拦截）
"""
import time
import ccxt

# 周期 → 毫秒
TF_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1w": 604_800_000,
}


def _fetch_klines_direct(symbol, timeframe, limit, since=None):
    """兜底：直连 fapi klines（绕过 ccxt 的 exchangeInfo/loadMarkets）"""
    import requests
    base = symbol.split(':')[0].replace('/', '')  # BTC/USDT:USDT -> BTCUSDT
    params = {'symbol': base, 'interval': timeframe, 'limit': limit}
    if since is not None:
        params['startTime'] = since
    r = requests.get('https://fapi.binance.com/fapi/v1/klines', params=params, timeout=10)
    r.raise_for_status()
    return [[int(row[0]), float(row[1]), float(row[2]), float(row[3]),
             float(row[4]), float(row[5])] for row in r.json()]


def _fetch_with_retry(symbol, timeframe, limit, since=None, retries=3, delay=1):
    last_err = None
    for attempt in range(retries):
        # 1) 优先 ccxt
        try:
            ex = ccxt.binance({"options": {"defaultType": "swap"}, "enableRateLimit": True})
            if since is not None:
                return ex.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            return ex.fetch_ohlcv(symbol, timeframe, limit=limit)
        except Exception as e:
            last_err = e
        # 2) ccxt 失败（WAF 挡 exchangeInfo）→ 直连 fapi
        try:
            return _fetch_klines_direct(symbol, timeframe, limit, since)
        except Exception as e:
            last_err = e
            time.sleep(delay * (attempt + 1))
    raise last_err


def main(params: dict) -> list:
    """
    拉取 Binance BTC 永续合约 OHLCV
    params:
        symbol: 交易对 (默认 BTC/USDT:USDT)
        timeframe: 周期 (默认 1h)
        limit: K线数量 (默认 200)
        until: (可选) 毫秒时间戳，只返回该时间之前的K线（用于历史回溯）
    返回: [{timestamp, open, high, low, close, volume}, ...]
    """
    symbol = params.get("symbol", "BTC/USDT:USDT")
    timeframe = params.get("timeframe", "1h")
    limit = params.get("limit", 200)
    until = params.get("until")

    if until:
        tf_ms = TF_MS.get(timeframe, 3_600_000)
        since = until - limit * tf_ms
        ohlcv = _fetch_with_retry(symbol, timeframe, limit, since=since)
        ohlcv = [row for row in ohlcv if row[0] < until]
    else:
        ohlcv = _fetch_with_retry(symbol, timeframe, limit)

    return [
        {
            "timestamp": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in ohlcv
    ]
