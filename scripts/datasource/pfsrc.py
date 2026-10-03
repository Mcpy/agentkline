NAME="性能源"
DESC="日内+日两档(e2e)"
PARAMS={"symbol":"X"}
CAPS={"backfill": False, "symbols": False, "ticker": True}
IDENTITY=["symbol"]
INTERVALS=["15m","1d"]
import time as _t
def main(params, until=None):
    return []
def ticker(params):
    return {"price": 1.0, "ts": int(_t.time()*1000)}
def tickers(pl):
    return [ticker(p) for p in pl]
