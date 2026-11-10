"""Minimal market-data request hub (v0.7.2).

Responsibilities, deliberately narrow:
- single-flight for the same (source, symbol/params, timeframe) key;
- short TTL cache so charts/paper sessions sharing a key do not refetch;
- per-source concurrency + requests/minute budget with 429/timeout backoff;
- observable counters used by /api/paper/runtime and MCP paper_runtime.

This is not a general event bus and does not merge different timeframes.
The value returned by ``fetch`` is the datasource script result ({"data": [...]})
and must be treated as read-only by callers.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger("agentkline.marketdata")

_TRANSIENT_MARKERS = (
    "429", "rate limit", "too many request", "too many requests", "timeout",
    "timed out", "connection", "ssl", "eof", "502", "503", "504",
    "temporarily", "unavailable", "network", "reset by peer",
)

def _as_float(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@dataclass
class _CacheEntry:
    value: dict
    at: float


@dataclass
class _Flight:
    event: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None
    done: bool = False


@dataclass
class _Source:
    name: str
    tokens: float
    refill_at: float
    inflight: int = 0
    requests: int = 0
    errors: int = 0
    rate_limited: int = 0
    consecutive_errors: int = 0
    backoff_s: float = 0.0
    backoff_until: float = 0.0
    latency_total_ms: float = 0.0
    latency_count: int = 0
    latency_max_ms: float = 0.0
    last_error: str | None = None
    last_request_at: float | None = None


class MarketDataHub:
    """Thread-safe request coalescer; one instance per AgentKlineService."""

    def __init__(self, limits: dict | None = None):
        limits = limits or {}
        self.ttl_active_s = max(0.0, _as_float(
            limits.get("market_ttl_active_s"), 4.0))
        self.ttl_idle_s = max(self.ttl_active_s, _as_float(
            limits.get("market_ttl_idle_s"), 30.0))
        self.max_inflight_per_source = max(1, int(_as_float(
            limits.get("market_max_inflight_per_source"), 4)))
        self.max_requests_per_min = max(1, int(_as_float(
            limits.get("market_max_requests_per_min"), 240)))
        self.budget_wait_s = max(1.0, _as_float(
            limits.get("market_budget_wait_s"), 15.0))
        self.backoff_base_s = max(0.1, _as_float(
            limits.get("market_backoff_base_s"), 2.0))
        self.backoff_max_s = max(self.backoff_base_s, _as_float(
            limits.get("market_backoff_max_s"), 60.0))

        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._cache: dict[str, _CacheEntry] = {}
        self._inflight: dict[str, _Flight] = {}
        self._sources: dict[str, _Source] = {}

        self._requests = 0
        self._cache_hits = 0
        self._inflight_hits = 0
        self._upstream = 0
        self._errors = 0
        self._rate_limited = 0
        self._backoff_skips = 0
        self._budget_timeouts = 0
        self._latency_total_ms = 0.0
        self._latency_max_ms = 0.0

    # ------------------------------ public ------------------------------
    def fetch(self, key: str, source: str, fn, ttl_s: float | None = None) -> dict:
        """Return a cached/single-flight result or an error dict.

        ``fn`` must be a zero-arg callable returning the datasource result dict.
        Errors are returned (not raised) so existing datasource error handling
        remains valid; transient errors trigger a per-source backoff.
        """
        key = str(key)
        source = str(source or "unknown")
        ttl = self.ttl_active_s if ttl_s is None else max(0.0, float(ttl_s))
        now = time.monotonic()

        with self._cond:
            self._requests += 1
            src = self._source(source, now)

            if src.backoff_until > now:
                self._backoff_skips += 1
                return self._backoff_error(src, now)

            ent = self._cache.get(key)
            if ent is not None and (now - ent.at) <= ttl:
                self._cache_hits += 1
                return ent.value

            flight = self._inflight.get(key)
            if flight is not None:
                self._inflight_hits += 1
                leader = False
            else:
                flight = _Flight()
                self._inflight[key] = flight
                leader = True
                # Reserve a source slot/token before doing any network work.
                if not self._acquire_source(src, now):
                    self._inflight.pop(key, None)
                    self._budget_timeouts += 1
                    return {
                        "error": "MARKET_BUDGET_WAIT: 数据源请求预算等待超时",
                        "code": "MARKET_BUDGET_WAIT",
                        "source": source,
                        "retry_after_s": 1.0,
                    }

        if not leader:
            # Wait for the in-flight leader; no lock held here.
            if not flight.event.wait(timeout=max(10.0, self.budget_wait_s + 30.0)):
                return {
                    "error": "MARKET_INFLIGHT_TIMEOUT: 等待同一行情请求超时",
                    "code": "MARKET_INFLIGHT_TIMEOUT",
                    "source": source,
                    "retry_after_s": 1.0,
                }
            return flight.result or {
                "error": "MARKET_INFLIGHT_EMPTY: 合并请求没有返回结果",
                "code": "MARKET_INFLIGHT_EMPTY",
                "source": source,
            }

        t0 = time.monotonic()
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - fetch boundary must not kill poll threads
            logger.warning("marketdata fetch exception %s: %r", source, exc)
            result = {"error": f"MARKET_FETCH_EXCEPTION: {exc}"}
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        if not isinstance(result, dict):
            result = {"error": f"MARKET_FETCH_INVALID: 返回 {type(result).__name__}"}

        now = time.monotonic()
        with self._cond:
            self._upstream += 1
            self._latency_total_ms += elapsed_ms
            self._latency_max_ms = max(self._latency_max_ms, elapsed_ms)
            src.latency_total_ms += elapsed_ms
            src.latency_count += 1
            src.latency_max_ms = max(src.latency_max_ms, elapsed_ms)
            src.last_request_at = now
            err = result.get("error")
            if err:
                self._errors += 1
                src.errors += 1
                src.last_error = str(err)[:500]
                src.consecutive_errors += 1
                if self._is_transient(err):
                    self._set_backoff(src, now)
                flight.result = result
            else:
                src.consecutive_errors = 0
                src.backoff_s = 0.0
                src.backoff_until = 0.0
                src.last_error = None
                self._cache[key] = _CacheEntry(value=result, at=now)
                self._prune_cache(now)
                flight.result = result
            flight.done = True
            flight.event.set()
            self._inflight.pop(key, None)
            self._release_source(src)
        return result

    def invalidate(self, key: str | None = None, prefix: str | None = None) -> int:
        """Drop cached entries (used after explicit source changes)."""
        with self._cond:
            if key is not None:
                return 1 if self._cache.pop(str(key), None) is not None else 0
            if prefix is None:
                return 0
            keys = [k for k in self._cache if k.startswith(str(prefix))]
            for k in keys:
                self._cache.pop(k, None)
            return len(keys)

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._cond:
            sources = {}
            for name, src in self._sources.items():
                sources[name] = {
                    "inflight": src.inflight,
                    "requests": src.requests,
                    "errors": src.errors,
                    "rate_limited": src.rate_limited,
                    "consecutive_errors": src.consecutive_errors,
                    "backoff_s": round(src.backoff_s, 3),
                    "backoff_remaining_s": round(max(0.0, src.backoff_until - now), 3),
                    "avg_latency_ms": round(src.latency_total_ms / src.latency_count, 1)
                    if src.latency_count else 0.0,
                    "max_latency_ms": round(src.latency_max_ms, 1),
                    "last_error": src.last_error,
                }
            return {
                "enabled": True,
                "ttl_active_s": self.ttl_active_s,
                "ttl_idle_s": self.ttl_idle_s,
                "max_inflight_per_source": self.max_inflight_per_source,
                "max_requests_per_min": self.max_requests_per_min,
                "cache_entries": len(self._cache),
                "inflight": len(self._inflight),
                "requests": self._requests,
                "upstream": self._upstream,
                "cache_hits": self._cache_hits,
                "inflight_hits": self._inflight_hits,
                "errors": self._errors,
                "rate_limited": self._rate_limited,
                "backoff_skips": self._backoff_skips,
                "budget_timeouts": self._budget_timeouts,
                "avg_latency_ms": round(
                    self._latency_total_ms / self._upstream, 1) if self._upstream else 0.0,
                "max_latency_ms": round(self._latency_max_ms, 1),
                "sources": sources,
            }

    # ------------------------------ internals ------------------------------
    def _source(self, name: str, now: float) -> _Source:
        src = self._sources.get(name)
        if src is None:
            src = _Source(name=name, tokens=float(self.max_requests_per_min), refill_at=now)
            self._sources[name] = src
        self._refill(src, now)
        return src

    def _refill(self, src: _Source, now: float) -> None:
        elapsed = max(0.0, now - src.refill_at)
        if elapsed <= 0:
            return
        src.tokens = min(
            float(self.max_requests_per_min),
            src.tokens + elapsed * (self.max_requests_per_min / 60.0))
        src.refill_at = now

    def _acquire_source(self, src: _Source, now: float) -> bool:
        """Wait for a token + concurrency slot; caller holds the condition lock."""
        deadline = now + self.budget_wait_s
        while True:
            self._refill(src, now)
            if src.backoff_until > now:
                return False
            if src.tokens >= 1.0 and src.inflight < self.max_inflight_per_source:
                src.tokens -= 1.0
                src.inflight += 1
                src.requests += 1
                return True
            if now >= deadline:
                return False
            if src.tokens < 1.0:
                need = (1.0 - src.tokens) / max(0.001, self.max_requests_per_min / 60.0)
                wait_s = min(0.25, max(0.01, need))
            else:
                wait_s = 0.05
            self._cond.wait(timeout=wait_s)
            now = time.monotonic()

    def _release_source(self, src: _Source) -> None:
        src.inflight = max(0, src.inflight - 1)
        self._cond.notify_all()

    def _set_backoff(self, src: _Source, now: float) -> None:
        if src.last_error and "429" in src.last_error:
            src.rate_limited += 1
            self._rate_limited += 1
        exp = min(6, max(0, src.consecutive_errors - 1))
        delay = min(self.backoff_max_s, self.backoff_base_s * (2 ** exp))
        delay *= random.uniform(0.75, 1.25)
        src.backoff_s = delay
        src.backoff_until = now + delay
        logger.warning("marketdata backoff source=%s delay=%.1fs err=%s",
                       src.name, delay, (src.last_error or "")[:160])

    def _backoff_error(self, src: _Source, now: float) -> dict:
        remaining = max(0.0, src.backoff_until - now)
        return {
            "error": (f"MARKET_BACKOFF: 数据源退避中，{remaining:.1f}s 后重试"
                      + (f"（{src.last_error}）" if src.last_error else "")),
            "code": "MARKET_BACKOFF",
            "retry_after_s": round(remaining, 2),
        }

    @staticmethod
    def _is_transient(err) -> bool:
        text = str(err or "").lower()
        return any(m in text for m in _TRANSIENT_MARKERS)

    def _prune_cache(self, now: float) -> None:
        # Keep cache memory bounded even if callers use many one-off keys.
        if len(self._cache) <= 256:
            return
        cutoff = now - max(300.0, self.ttl_idle_s * 4)
        for k, ent in list(self._cache.items()):
            if ent.at < cutoff:
                self._cache.pop(k, None)
