"""A 股实时数据源（builtin）。

主厂商=东方财富（push2his K线 / push2 ulist 实时 / searchapi suggest 搜索）；
备厂商=腾讯 gtimg 族（ifzq fqkline K线 / qt.gtimg 实时）——主厂商被限流/封锁时自动回落。
symbol 格式：600519.SH / 000001.SZ（代码.交易所；内部映射东财 secid 1./0. 与腾讯 sh/sz 前缀）。
"""
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

NAME = "A股·免费多源"
DESC = "中国 A 股实时行情：K线全周期+前/后复权、批量实时报价、代码/名称搜索；多厂商免费接口互备（东财/腾讯/新浪自动回落）"
PARAMS = {"fqt": 1}
INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d", "1w", "1mo"]
CAPS = {"backfill": True, "symbols": True, "ticker": True}
IDENTITY = ["symbol"]

_TZ = timezone(timedelta(hours=8))
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
_KLT = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 101, "1w": 102, "1mo": 103}
# 分钟级回补跨度估计（日历日），覆盖约千根；日级及以上取全历史
_BAR_MIN = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440, "1w": 10080, "1mo": 43200}


def _span_days(interval, depth):
    """按请求根数推算日历跨度（含缓冲）；回补/实时共用。"""
    return int(depth * _BAR_MIN.get(interval, 1440) / 1440.0 * 1.6) + 5
_CACHE = {}          # (key) -> (ts, value)：源内最小间隔礼貌缓存
_CACHE_TTL = 3.0


def _get(url, timeout=8):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return raw


def _get_json(url, timeout=8):
    return json.loads(_get(url, timeout).decode("utf-8", "replace"))


def _cached(key, fn):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val


def _split_symbol(symbol):
    """600519.SH -> (code, 'SH')；非法返回 None。"""
    if not symbol or "." not in symbol:
        return None
    code, _, ex = symbol.partition(".")
    ex = ex.upper()
    if ex not in ("SH", "SZ") or not code.isdigit():
        return None
    return code, ex


def _secid(symbol):
    p = _split_symbol(symbol)
    if not p:
        return None
    code, ex = p
    return ("1." if ex == "SH" else "0.") + code


def _tx_symbol(symbol):
    p = _split_symbol(symbol)
    if not p:
        return None
    code, ex = p
    return ("sh" if ex == "SH" else "sz") + code


def _ts_ms(text, interval):
    """K线时间文本 -> 毫秒（Asia/Shanghai 本地语义）。"""
    text = text.strip()
    if len(text) <= 10:
        dt = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=_TZ)
    else:
        dt = datetime.strptime(text[:16], "%Y-%m-%d %H:%M").replace(tzinfo=_TZ)
    return int(dt.timestamp() * 1000)


# ── K线：东财主 ──
def _kline_em(symbol, interval, until):
    sid = _secid(symbol)
    if not sid:
        return []
    klt = _KLT[interval]
    if until is not None:
        end_dt = datetime.fromtimestamp((until - 1) / 1000, _TZ)
    else:
        end_dt = datetime.now(_TZ)
    end = end_dt.strftime("%Y%m%d")
    beg = (end_dt - timedelta(days=_span_days(interval, _DEPTH[0]))).strftime("%Y%m%d")
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=%s&klt=%d&fqt=%d"
           "&beg=%s&end=%s&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56"
           % (sid, klt, _FQT[0], beg, end))
    d = _get_json(url)
    kl = (d.get("data") or {}).get("klines") or []
    bars = []
    for row in kl:
        f = row.split(",")
        ts = _ts_ms(f[0], interval)
        if until is not None and ts >= until:
            continue
        bars.append({"timestamp": ts, "open": float(f[1]), "close": float(f[2]),
                     "high": float(f[3]), "low": float(f[4]), "volume": float(f[5])})
    return bars


# ── K线：腾讯备 ──
def _kline_tx(symbol, interval, until):
    tsym = _tx_symbol(symbol)
    if not tsym:
        return []
    tx_iv = {"1h": "60m", "1mo": "month"}.get(interval, interval)
    kind = "day" if interval == "1d" else ("week" if interval == "1w" else tx_iv)
    if until is not None:
        end_dt = datetime.fromtimestamp((until - 1) / 1000, _TZ)
        end = end_dt.strftime("%Y-%m-%d")
        beg = (end_dt - timedelta(days=_span_days(interval, _DEPTH[0]))).strftime("%Y-%m-%d")
    else:
        end, beg = "", ""
    qfq = "qfq" if _FQT[0] == 1 else ("hfq" if _FQT[0] == 2 else "")
    param = "%s,%s,%s,%s,%d,%s" % (tsym, kind, beg, end, _DEPTH[0], qfq)
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s" % urllib.parse.quote(param)
    d = _get_json(url)
    node = (d.get("data") or {}).get(tsym) or {}
    rows = node.get("qfq" + kind) or node.get(kind) or []
    bars = []
    for f in rows:
        ts = _ts_ms(f[0], interval)
        if until is not None and ts >= until:
            continue
        bars.append({"timestamp": ts, "open": float(f[1]), "close": float(f[2]),
                     "high": float(f[3]), "low": float(f[4]), "volume": float(f[5])})
    return bars


# ── K线分钟级：新浪备（腾讯 ifzq 无分钟级） ──
_SINA_SCALE = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 240}


def _kline_sina(symbol, interval, until, count=1000):
    tsym = _tx_symbol(symbol)
    if not tsym or interval not in _SINA_SCALE:
        return []
    url = ("https://quotes.sina.cn/cn/api/jsonp_v2.php/var%%20d=/CN_MarketDataService.getKLineData"
           "?symbol=%s&scale=%d&ma=no&datalen=%d" % (tsym, _SINA_SCALE[interval], count))
    text = _get(url).decode("utf-8", "replace")
    i, j = text.find("(["), text.rfind("])")
    if i < 0 or j < 0:
        return []
    rows = json.loads(text[i + 1:j + 1])
    bars = []
    for f in rows:
        ts = _ts_ms(f["day"], interval)
        if until is not None and ts >= until:
            continue
        bars.append({"timestamp": ts, "open": float(f["open"]), "close": float(f["close"]),
                     "high": float(f["high"]), "low": float(f["low"]), "volume": float(f["volume"])})
    return bars


_FQT = [1]   # 当前 main 调用的复权档（_kline_* 闭包读取）
_DEPTH = [200]  # 当前 main 调用的请求根数（limit；请求层收口，非客户端丢弃）


def main(params, until=None):
    symbol = params.get("symbol", "")
    interval = params.get("interval", "1d")
    if interval not in _KLT:
        return []
    _FQT[0] = int(params.get("fqt", 1))
    _DEPTH[0] = int(params.get("limit", 200))
    key = ("k", symbol, interval, until, _FQT[0], _DEPTH[0])
    # 厂商链：东财主 → 分钟级新浪备 / 日级及以上腾讯备
    if interval in _SINA_SCALE:
        # 分钟+日级：新浪备。until=None：count=请求根数直达 datalen（无浪费）；
        # until≠None：新浪无终点参数=厂商固定行为——固定拉 1970 深度+过滤+尾截 limit
        # （"拉多丢"浪费仅限此备路径回补，用户裁决接受）
        if until is None:
            backups = ((lambda sym, iv, un: _kline_sina(sym, iv, un, _DEPTH[0])),)
        else:
            backups = ((lambda sym, iv, un: _kline_sina(sym, iv, un, 1970)[-_DEPTH[0]:]),)
    elif until is None:
        backups = (_kline_tx,)          # 周/月级实时：腾讯备
    else:
        backups = ()                    # 周/月级回补：仅东财（封墙期临时降级）

    def fetch():
        try:
            bars = _kline_em(symbol, interval, until)
            if bars:
                return bars
        except Exception:
            pass
        for fn in backups:
            try:
                bars = fn(symbol, interval, until)
                if bars:
                    return bars
            except Exception:
                continue
        return []
    bars = _cached(key, fetch)
    if until is None:
        depth = int(params.get("limit", 200))
        if len(bars) > depth:
            bars = bars[-depth:]
    return bars


# ── 实时报价：东财主 / 腾讯备 ──
def _quote_em(sid):
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get?secids=%s"
           "&fields=f2,f3,f12,f14&fltt=2" % sid)
    d = _get_json(url)
    diff = (d.get("data") or {}).get("diff") or []
    if not diff:
        return None
    x = diff[0]
    price = x.get("f2")
    if price is None or price == "-":
        return None
    return {"price": float(price), "ts": int(time.time() * 1000),
            "change_pct": float(x.get("f3") or 0)}


def _quote_tx(tsym):
    raw = _get("https://qt.gtimg.cn/q=%s" % tsym)
    text = raw.decode("gbk", "replace")
    body = text.split('"', 1)[1] if '"' in text else ""
    f = body.split("~")
    if len(f) < 35:
        return None
    price = float(f[3])
    if price <= 0:
        return None
    return {"price": price, "ts": int(time.time() * 1000), "change_pct": float(f[32] or 0)}


def ticker(params):
    symbol = params.get("symbol", "")
    sid, tsym = _secid(symbol), _tx_symbol(symbol)
    if not sid:
        return {"price": 0.0, "ts": int(time.time() * 1000)}

    def fetch():
        for fn, arg in ((_quote_em, sid), (_quote_tx, tsym)):
            try:
                q = fn(arg)
                if q:
                    return q
            except Exception:
                continue
        return {"price": 0.0, "ts": int(time.time() * 1000)}
    return _cached(("t", symbol), fetch)


def tickers(params_list):
    out = []
    for p in params_list:
        out.append(ticker(p))
    return out


# ── 全量列表：新浪 Market_Center 分页（索引首用；东财 push2 族对机房出口有限流） ──
def _full_list():
    # sina num 上限 100；并发分页（首用索引否则串行 40+ 页太慢）
    from concurrent.futures import ThreadPoolExecutor
    MAXP = 40

    def fetch(node, page):
        url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               "Market_Center.getHQNodeData?page=%d&num=100&sort=symbol&asc=1&node=%s" % (page, node))
        try:
            return json.loads(_get(url, timeout=10).decode("utf-8", "replace")) or []
        except Exception:
            return []

    out = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for node, exch in (("sh_a", "SH"), ("sz_a", "SZ")):
            futs = {ex.submit(fetch, node, p): p for p in range(1, MAXP + 1)}
            pages = {}
            for f in futs:
                pages[futs[f]] = f.result()
            for p in sorted(pages):
                rows = pages[p]
                if not rows:
                    break
                for x in rows:
                    out.append({"symbol": "%s.%s" % (x.get("code"), exch),
                                "display": "%s %s" % (x.get("name"), x.get("code"))})
    return out


# ── 搜索：空 query=全量（索引首用）；非空=东财 suggest 实时（直调 fallback） ──
def list_symbols(query):
    q = (query or "").strip()
    if not q:
        return _full_list()
    url = ("https://searchapi.eastmoney.com/api/suggest/get?input=%s&type=14"
           "&token=D43BF722C8E33BDC906FB84D85E326E8&count=20" % urllib.parse.quote(q))
    try:
        d = _get_json(url)
    except Exception:
        return []
    rows = ((d.get("QuotationCodeTable") or {}).get("Data")) or []
    out = []
    for x in rows:
        if x.get("Classify") != "AStock":
            continue
        mkt = x.get("SecurityTypeName") or ""
        ex = "SH" if "沪" in mkt else ("SZ" if "深" in mkt else None)
        if not ex:
            continue
        out.append({"symbol": "%s.%s" % (x.get("Code"), ex),
                    "display": "%s %s" % (x.get("Name"), x.get("Code"))})
    return out
