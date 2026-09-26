"""
数据源：Binance 永续合约（ccxt + 直连兜底）
符号参数化；支持标的搜索(list_symbols)/实时报价(ticker)/历史回溯(until)
含重试逻辑（Binance 有间歇性 WAF 拦截，ccxt 失败时直连 fapi）
"""
import time

NAME = "Binance 永续 (ccxt)"
DESC = "Binance USDT 永续合约 K 线；symbol 参数化；支持搜索/报价/回溯"
PARAMS = {"symbol": "BTC/USDT:USDT", "interval": "1d", "limit": 200}
CAPS = {"backfill": True, "symbols": True, "ticker": True}
IDENTITY = ["symbol"]
# 支持周期表（Binance 永续全档）；建板默认取 [15m,1h,4h,1d,1w] ∩ 本表
INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h",
             "12h", "1d", "3d", "1w", "1M"]

# 周期 → 毫秒
TF_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1w": 604_800_000,
}


def _base(symbol: str) -> str:
    """BTC/USDT:USDT -> BTCUSDT"""
    return symbol.split(':')[0].replace('/', '')


def _fetch_klines_direct(symbol, timeframe, limit, since=None):
    """兜底：直连 fapi klines（绕过 ccxt 的 exchangeInfo/loadMarkets）"""
    import requests
    params = {'symbol': _base(symbol), 'interval': timeframe, 'limit': limit}
    if since is not None:
        params['startTime'] = since
    r = requests.get('https://fapi.binance.com/fapi/v1/klines', params=params, timeout=10)
    r.raise_for_status()
    return [[int(row[0]), float(row[1]), float(row[2]), float(row[3]),
             float(row[4]), float(row[5])] for row in r.json()]


def _fetch_with_retry(symbol, timeframe, limit, since=None, retries=3, delay=1):
    last_err = None
    for attempt in range(retries):
        # 1) 优先 ccxt（import 放 try 内：缺失时走直连兜底）
        try:
            import ccxt
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


def main(params: dict, until=None) -> list:
    """
    拉取 Binance 永续 OHLCV
    params: symbol / interval(系统注入) / limit
    until: 毫秒时间戳，只返回该时间之前的K线（历史回溯，调用参数不受板锁）
    """
    symbol = params.get("symbol", "BTC/USDT:USDT")
    # interval 由系统按槽位注入（§2.2）；缺省 1d 与周期槽语义一致
    timeframe = params.get("interval", params.get("timeframe", "1d"))
    limit = int(params.get("limit", 200))

    if until:
        tf_ms = TF_MS.get(timeframe, 3_600_000)
        since = int(until) - limit * tf_ms
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


def list_symbols(query: str = "") -> list:
    """标的搜索：直连 exchangeInfo（永不穿透 ccxt 的 markets 缓存问题）"""
    import requests
    r = requests.get('https://fapi.binance.com/fapi/v1/exchangeInfo', timeout=10)
    r.raise_for_status()
    q = (query or "").upper().strip()
    out = []
    for s in r.json().get("symbols", []):
        if s.get("contractType") != "PERPETUAL" or s.get("status") != "TRADING":
            continue
        if s.get("quoteAsset") != "USDT":
            continue
        sym = f"{s['baseAsset']}/USDT:USDT"
        if q and q not in sym.upper():
            continue
        out.append({"symbol": sym, "display": f"{s['baseAsset']}/USDT 永续"})
        if len(out) >= 200:
            break
    return out


def ticker(params: dict) -> dict:
    """实时报价：24h ticker（last/涨跌/涨跌%）"""
    import requests
    symbol = params.get("symbol", "BTC/USDT:USDT")
    r = requests.get('https://fapi.binance.com/fapi/v1/ticker/24hr',
                     params={'symbol': _base(symbol)}, timeout=10)
    r.raise_for_status()
    d = r.json()
    import time as _t
    return {
        "price": float(d["lastPrice"]),
        "ts": int(_t.time() * 1000),
        "change_pct": float(d["priceChangePercent"]),
        "extra": {"change": float(d["priceChange"]), "high": float(d["highPrice"]),
                  "low": float(d["lowPrice"]), "quote_volume": float(d["quoteVolume"])},
    }


def tickers(params_list: list) -> list:
    """批量报价（性能②）：一次 fapi 24hr 请求拿全部盯盘符号（symbols 数组，权重远低于逐行）"""
    import requests, time as _t, json as _json
    bases = [_base(p.get("symbol", "BTC/USDT:USDT")) for p in params_list]
    r = requests.get('https://fapi.binance.com/fapi/v1/ticker/24hr',
                     params={'symbols': _json.dumps(bases)}, timeout=10)
    r.raise_for_status()
    by_sym = {d["symbol"]: d for d in r.json()}
    ts = int(_t.time() * 1000)
    out = []
    for b in bases:
        d = by_sym.get(b)
        if not d:
            out.append({"price": 0.0, "ts": ts})
            continue
        out.append({"price": float(d["lastPrice"]), "ts": ts,
                    "change_pct": float(d["priceChangePercent"]),
                    "extra": {"change": float(d["priceChange"]), "high": float(d["highPrice"]),
                              "low": float(d["lowPrice"]), "quote_volume": float(d["quoteVolume"])}})
    return out
