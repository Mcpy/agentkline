#!/usr/bin/env python3
"""MarketDataHub 单测（0.7.2）：single-flight / TTL / timeframe 隔离 / 429 退避 / 预算。

无 pytest 依赖：.venv/bin/python tools/test_marketdata_unit.py
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkline.core.marketdata import MarketDataHub
from agentkline.core.datasource import DataSourceManager

ok = 0
bad = []


def check(name, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        bad.append(name)
        print(f"  ❌ {name} {detail}")


def main():
    # 10 个消费者同时请求同一 key：只允许一次上游请求
    hub = MarketDataHub({"market_ttl_active_s": 5.0, "market_max_requests_per_min": 600,
                         "market_max_inflight_per_source": 4})
    calls = []
    lock = threading.Lock()
    barrier = threading.Barrier(10)

    def slow_fetch():
        with lock:
            calls.append(1)
        time.sleep(0.15)
        return {"data": [{"timestamp": 1, "close": 2.0}]}

    out = []

    def same_key():
        barrier.wait()
        out.append(hub.fetch("same|1h", "src", slow_fetch))

    ts = [threading.Thread(target=same_key) for _ in range(10)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    snap = hub.snapshot()
    check("10 消费者同 key 上游只请求 1 次", len(calls) == 1, f"calls={len(calls)}")
    check("10 消费者都拿到结果", len(out) == 10 and all(x.get("data") for x in out), str(out[:1]))
    check("指标记录 inflight 合并", snap["inflight_hits"] == 9 and snap["upstream"] == 1,
          str(snap))

    # TTL 内命中缓存，不再请求
    before = len(calls)
    hub.fetch("same|1h", "src", slow_fetch)
    check("TTL 内缓存命中", len(calls) == before and hub.snapshot()["cache_hits"] >= 1)

    # 不同 timeframe 不合并
    calls.clear()
    hub.fetch("same|4h", "src", slow_fetch)
    check("不同周期独立请求", len(calls) == 1, f"calls={len(calls)}")

    # TTL 过期后重取
    tiny = MarketDataHub({"market_ttl_active_s": 0.05, "market_ttl_idle_s": 0.05,
                         "market_max_requests_per_min": 600})
    calls2 = []
    def tick():
        calls2.append(1)
        return {"data": [1]}
    tiny.fetch("t|1h", "src", tick)
    time.sleep(0.08)
    tiny.fetch("t|1h", "src", tick)
    check("TTL 过期后重取", len(calls2) == 2, f"calls={len(calls2)}")

    # 429 退避：同一源后续请求直接返回 MARKET_BACKOFF，不继续打上游
    backoff = MarketDataHub({"market_ttl_active_s": 0.01,
                            "market_backoff_base_s": 0.3,
                            "market_backoff_max_s": 0.3,
                            "market_max_requests_per_min": 600})
    err_calls = []
    def rate_limited():
        err_calls.append(1)
        return {"error": "HTTP 429 Too Many Requests"}
    first = backoff.fetch("e|1h", "bad", rate_limited)
    second = backoff.fetch("e2|1h", "bad", rate_limited)
    check("429 首次返回错误", first.get("error") and "429" in first["error"], str(first))
    check("429 后续进入退避且不打上游",
          len(err_calls) == 1 and second.get("code") == "MARKET_BACKOFF", str(second))
    bs = backoff.snapshot()
    check("指标记录 429 与退避",
          bs["rate_limited"] == 1 and bs["backoff_skips"] == 1
          and bs["sources"]["bad"]["backoff_s"] > 0, str(bs))

    # 预算：每分钟 2 次 + 并发 1，第三个不同 key 等不到预算
    budget = MarketDataHub({"market_ttl_active_s": 0.01,
                           "market_max_requests_per_min": 2,
                           "market_max_inflight_per_source": 1,
                           "market_budget_wait_s": 0.25})
    bcalls = []
    def bfetch():
        bcalls.append(1)
        time.sleep(0.12)
        return {"data": [1]}
    bout = []
    bbar = threading.Barrier(3)
    def bworker(i):
        bbar.wait()
        bout.append(budget.fetch(f"b{i}|1h", "budget", bfetch))
    ts = [threading.Thread(target=bworker, args=(i,)) for i in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("预算只放行 2 次上游", len(bcalls) == 2, f"calls={len(bcalls)}")
    check("超预算返回结构化错误",
          any(x.get("code") == "MARKET_BUDGET_WAIT" for x in bout), str(bout))
    check("指标记录预算等待", budget.snapshot()["budget_timeouts"] >= 1)

    # OHLCV 合并：timestamp 去重 + 排序，重复 bar 不进入 paper 时间轴
    merged = DataSourceManager._merge_ohlcv(
        [{"timestamp": 3, "close": 3.0}, {"timestamp": 1, "close": 1.0}],
        [{"timestamp": 2, "close": 2.0}, {"timestamp": 2, "close": 2.5},
         {"timestamp": 3, "close": 3.5}])
    check("merge 按 timestamp 去重排序",
          [b["timestamp"] for b in merged] == [1, 2, 3]
          and merged[1]["close"] == 2.5 and merged[2]["close"] == 3.5, str(merged))
    k1 = DataSourceManager._hub_key("datasource/binance", {"symbol": "BTC", "interval": "1h"}, "1h")
    k2 = DataSourceManager._hub_key("datasource/binance", {"interval": "1h", "symbol": "BTC"}, "1h")
    k3 = DataSourceManager._hub_key("datasource/binance", {"symbol": "BTC", "interval": "1h"}, "4h")
    check("hub key 参数顺序无关", k1 == k2)
    check("hub key 区分 timeframe", k1 != k3)

    # DataSourceManager 实际取数路径也走 Hub：10 个消费者同 key 只打 1 次
    class FakeEngine:
        def __init__(self):
            self.calls = 0
            self.lock = threading.Lock()
        def run_script(self, script, params, until=None):
            with self.lock:
                self.calls += 1
            time.sleep(0.12)
            return {"data": [{"timestamp": 1, "close": 1.0}]}
    fe = FakeEngine()
    dh = MarketDataHub({"market_ttl_active_s": 5.0, "market_max_requests_per_min": 600})
    ds = DataSourceManager(None, fe, None, hub=dh)
    dbar = threading.Barrier(10)
    def dworker():
        dbar.wait()
        ds._fetch("datasource/fake", {"symbol": "BTC", "interval": "1h"}, "1h")
    ts = [threading.Thread(target=dworker) for _ in range(10)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("DataSource 路径同 key 只请求 1 次", fe.calls == 1, f"calls={fe.calls}")

    print(f"\nMarketDataHub: {ok} passed, {len(bad)} failed")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
