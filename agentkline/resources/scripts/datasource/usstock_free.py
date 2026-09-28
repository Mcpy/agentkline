"""美股实时数据源（builtin）。

主厂商=Yahoo（v8 chart K线 period 回补 / v8 spark 批量实时 / v1 search 搜索）；
备厂商=腾讯 gtimg 族（ifzq 日/周/月 K线 / qt 实时）；
全量索引=东方财富美股 clist 分页（并发）。
symbol 格式：AAPL.US（代码.US；内部映射 Yahoo 裸码与腾讯 us 前缀）。
Yahoo 分钟级有 vendor 范围上限（1m≤7d、5m/15m/30m≤60d、1h≤730d），回补到边界返空=有界语义。
"""
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

NAME = "美股·免费多源"
DESC = "美股实时行情：K线全周期(Yahoo 单厂商,免费美股K线业界稀缺)+实时互备(spark→腾讯qt)+名称搜索；索引=精选宇宙(S&P500+Nasdaq100)；默认不复权"
PARAMS = {"fqt": 0}
INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d", "1w", "1mo"]
CAPS = {"backfill": True, "symbols": True, "ticker": True}
IDENTITY = ["symbol"]

_TZ = timezone.utc
_UA = {"User-Agent": "Mozilla/5.0"}  # 短 UA：Yahoo 对本 IP+全 Chrome UA（无配套 client-hints）组合黑名单 429，短 UA 无指纹期望可过（实测矩阵）
_Y_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]  # 429 按 host 计→轮换
_Y_HOST_IX = [0]
_YIV = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h",
        "1d": "1d", "1w": "1wk", "1mo": "1mo"}
_BAR_MIN = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440, "1w": 10080, "1mo": 43200}
# Yahoo 分钟级 vendor 范围上限（日历天）
_Y_SPAN_CAP = {"1m": 7, "5m": 60, "15m": 60, "30m": 60, "1h": 730}
_CACHE = {}
_CACHE_TTL = 3.0
_FQT = [0]
_DEPTH = [200]


_HOST_LAST = {}  # host 级最小间隔礼貌限流（多板并发轮询防再踩 429）
_HOST_MIN_GAP = {"query1.finance.yahoo.com": 2.0, "query2.finance.yahoo.com": 2.0}


def _polite(url):
    from urllib.parse import urlparse
    host = urlparse(url).netloc
    gap = _HOST_MIN_GAP.get(host)
    if not gap:
        return
    now = time.time()
    last = _HOST_LAST.get(host, 0)
    if now - last < gap:
        time.sleep(gap - (now - last))
    _HOST_LAST[host] = time.time()


def _get(url, timeout=8):
    # v0.4.4：subprocess curl 优先——Yahoo 按 TLS 指纹(JA3) 拦 python ssl（全浏览器头也 429），
    # 系统 curl 指纹可过；list-form args 无 shell 注入；urllib 兜底（其他厂商无此问题）
    import subprocess, urllib.error
    _polite(url)
    for attempt in (0, 1, 2):
        try:
            r = subprocess.run(["curl", "-s", "--compressed", "--max-time", str(timeout),
                                "-A", _UA["User-Agent"], "-w", "\n%{http_code}", url],
                               capture_output=True, timeout=timeout + 3)
            if r.returncode == 0:
                out = r.stdout.decode("utf-8", "replace")
                body, _, code = out.rpartition("\n")
                if code.strip() == "429" and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                if code.strip() in ("200", "203"):
                    return body.encode("utf-8")
                raise urllib.error.HTTPError(url, int(code.strip() or 0), "http", None, None)
        except FileNotFoundError:
            break  # 无 curl 二进制 → urllib 兜底
        except subprocess.TimeoutExpired:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


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


def _bare(symbol):
    """AAPL.US -> AAPL；非法 None。"""
    if not symbol or "." not in symbol:
        return None
    code, _, ex = symbol.partition(".")
    return code if ex.upper() == "US" and code else None


def _span_days(interval, depth):
    est = int(depth * _BAR_MIN.get(interval, 1440) / 1440.0 * 1.6) + 5
    cap = _Y_SPAN_CAP.get(interval)
    return min(est, cap) if cap else est


# ── K线：Yahoo 主 ──
def _yh_url(path):
    host = _Y_HOSTS[_Y_HOST_IX[0]]
    return "https://%s%s" % (host, path)


def _yh_rotate():
    _Y_HOST_IX[0] = (_Y_HOST_IX[0] + 1) % len(_Y_HOSTS)


def _kline_yh(symbol, interval, until):
    bare = _bare(symbol)
    if not bare:
        return []
    if until is not None:
        p2 = (until - 1) // 1000
    else:
        p2 = int(time.time())
    p1 = p2 - _span_days(interval, _DEPTH[0]) * 86400
    url = _yh_url("/v8/finance/chart/%s?interval=%s&period1=%d&period2=%d"
                  % (urllib.parse.quote(bare), _YIV[interval], p1, p2))
    try:
        d = _get_json(url)
    except Exception:
        _yh_rotate()
        d = _get_json(_yh_url("/v8/finance/chart/%s?interval=%s&period1=%d&period2=%d"
                              % (urllib.parse.quote(bare), _YIV[interval], p1, p2)))
    res = ((d.get("chart") or {}).get("result") or [None])[0]
    if not res:
        return []
    ts_arr = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    o, h, l, c, v = (q.get(k) or [] for k in ("open", "high", "low", "close", "volume"))
    adj = ((res.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
    bars = []
    for i, ts in enumerate(ts_arr):
        if i >= len(c) or c[i] is None:
            continue  # Yahoo null 洞跳过
        close = adj[i] if (_FQT[0] == 1 and i < len(adj) and adj[i] is not None) else c[i]
        bars.append({"timestamp": int(ts) * 1000, "open": o[i] if i < len(o) and o[i] is not None else close,
                     "high": h[i] if i < len(h) and h[i] is not None else close,
                     "low": l[i] if i < len(l) and l[i] is not None else close,
                     "close": close, "volume": float(v[i] or 0) if i < len(v) else 0.0})
    return bars


def main(params, until=None):
    symbol = params.get("symbol", "")
    interval = params.get("interval", "1d")
    if interval not in _YIV:
        return []
    _FQT[0] = int(params.get("fqt", 0))
    _DEPTH[0] = int(params.get("limit", 200))
    key = ("k", symbol, interval, until, _FQT[0], _DEPTH[0])
    backups = ()  # 美股 K线 Yahoo 单厂商（腾讯 ifzq 美股日K 坏数据、东财封墙；业界同 yfinance 现实）

    def fetch():
        try:
            bars = _kline_yh(symbol, interval, until)
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
    if until is None and len(bars) > _DEPTH[0]:
        bars = bars[-_DEPTH[0]:]
    return bars


# ── 实时：Yahoo spark 批量主 / 腾讯 qt 备 ──
def _spark_quote(bare):
    url = _yh_url("/v8/finance/spark?symbols=%s&range=1d&interval=5m" % urllib.parse.quote(bare))
    d = _get_json(url)
    x = d.get(bare) or {}
    closes = x.get("close") or []
    if not closes or closes[-1] is None:
        return None
    prev = x.get("previousClose")
    price = float(closes[-1])
    pct = round((price - prev) / prev * 100, 4) if prev else 0.0
    ts = (x.get("end") or int(time.time())) * 1000
    return {"price": price, "ts": int(ts), "change_pct": pct}


def _quote_tx(bare):
    raw = _get("https://qt.gtimg.cn/q=us%s" % bare)
    f = raw.decode("gbk", "replace").split("~")
    if len(f) < 35 or float(f[3] or 0) <= 0:
        return None
    return {"price": float(f[3]), "ts": int(time.time() * 1000), "change_pct": float(f[32] or 0)}


def ticker(params):
    bare = _bare(params.get("symbol", ""))
    if not bare:
        return {"price": 0.0, "ts": int(time.time() * 1000)}

    def fetch():
        for fn in (_spark_quote, _quote_tx):
            try:
                q = fn(bare)
                if q:
                    return q
            except Exception:
                continue
        return {"price": 0.0, "ts": int(time.time() * 1000)}
    return _cached(("t", bare), fetch)


def tickers(params_list):
    # spark 真批量：单请求多符号
    bares = []
    for p in params_list:
        b = _bare(p.get("symbol", ""))
        bares.append(b)
    uniq = [b for b in dict.fromkeys(bares) if b]
    quotes = {}
    if uniq:
        try:
            url = _yh_url("/v8/finance/spark?symbols=%s&range=1d&interval=5m"
                          % urllib.parse.quote(",".join(uniq)))
            d = _get_json(url)
            for b in uniq:
                x = d.get(b) or {}
                closes = x.get("close") or []
                if closes and closes[-1] is not None:
                    prev = x.get("previousClose")
                    price = float(closes[-1])
                    quotes[b] = {"price": price, "ts": int((x.get("end") or time.time()) * 1000),
                                 "change_pct": round((price - prev) / prev * 100, 4) if prev else 0.0}
        except Exception:
            pass
    out = []
    for b in bares:
        q = quotes.get(b)
        if not q:
            q = ticker({"symbol": (b + ".US") if b else ""})
        out.append(q)
    return out


# ── 搜索：Yahoo v1 ──
def list_symbols(query):
    q = (query or "").strip()
    if not q:
        return _full_list()
    url = _yh_url("/v1/finance/search?q=%s&quotesCount=20&newsCount=0" % urllib.parse.quote(q))
    try:
        d = _get_json(url)
    except Exception:
        return []
    out = []
    for x in (d.get("quotes") or []):
        if x.get("quoteType") != "EQUITY" or not x.get("symbol"):
            continue
        out.append({"symbol": "%s.US" % x["symbol"],
                    "display": "%s %s" % (x.get("shortname") or x["symbol"], x["symbol"])})
    return out


# ── 索引宇宙：Wikipedia S&P500 + Nasdaq-100 种子（精选非全量；东财 clist 并发即封弃用） ──
_WIKI = ["https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
         "https://en.wikipedia.org/wiki/Nasdaq-100"]


def _full_list():
    import re as _re
    seen = {}
    for url in _WIKI:
        try:
            html = _get(url, timeout=10).decode("utf-8", "replace")
        except Exception:
            continue
        # 行级：symbol 列 + 公司名列（S&P500/Nasdaq100 表结构同构）
        for sym, name in _re.findall(
                r">([A-Z][A-Z0-9.\-]{0,6})</a></td>\s*<td[^>]*>(?:<a[^>]*>)?([^<]{1,60}?)(?:</a>)?</td>", html):
            if sym not in seen:
                seen[sym] = ("%s.US" % sym, "%s %s" % (name.strip(), sym))
    return [{"symbol": v[0], "display": v[1]} for v in seen.values()]
