"""
v0.4.1 雷达：WatchlistManager。
结构第一天 groups[] → rows[]（0.4.2 分组 UI 零重构接入；0.4.1 仅默认组）。
三态分发：visible（行=当前锁定板→quote 心跳事件）/ hidden（有板非当前→缓存+未读计数）/ watch（无板→仅面板）。
quotes 轮询默认 5s（config limits.quotes_poll_s 可调）；行级失败不炸整轮，连续 10 次失败标 stale。
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor


class WatchlistManager:
    def __init__(self, service, poll_s=5):
        self.svc = service
        self.poll_s = poll_s
        self.groups = [{"id": "default", "name": "默认", "rows": []}]
        self.quotes = {}          # row_key -> {price, change_pct, ts, state, fails, stale}（unread 已退役：三态点即全部信息）
        self._timer = None
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=8)

    # ---------- 行管理 ----------
    @staticmethod
    def key(source, symbol):
        return f"{source}|{symbol}"

    def add_row(self, source, symbol):
        r = self.svc.script_engine.ticker(source, {"symbol": symbol})
        if r.get("error"):
            return {"error": f"TICKER_UNSUPPORTED: {r['error']}（雷达只盯有 CAPS.ticker 的源）"}
        with self._lock:
            g = self.groups[0]
            if any(x["source"] == source and x["symbol"] == symbol for x in g["rows"]):
                return {"status": "ok", "noop": True}
            g["rows"].append({"source": source, "symbol": symbol})
            self.quotes.setdefault(self.key(source, symbol),
                                   {"price": None, "change_pct": None, "ts": None,
                                    "state": "watch", "fails": 0, "stale": False})
        self._ensure_polling()
        self._bc_changed()
        return {"status": "ok", "rows": len(self.groups[0]["rows"])}

    def has_row(self, source, symbol):
        return any(x["source"] == source and x["symbol"] == symbol
                   for g in self.groups for x in g["rows"])

    def remove_row(self, source, symbol):
        with self._lock:
            g = self.groups[0]
            before = len(g["rows"])
            g["rows"] = [x for x in g["rows"] if not (x["source"] == source and x["symbol"] == symbol)]
            self.quotes.pop(self.key(source, symbol), None)
            if len(g["rows"]) == before:
                return {"error": "ROW_NOT_FOUND: 雷达无此行"}
        self._bc_changed()
        return {"status": "ok", "rows": len(self.groups[0]["rows"])}

    def list_watchlist(self):
        return {"groups": [{**g, "rows": [self._row_view(x) for x in g["rows"]]} for g in self.groups]}

    def quotes_snapshot(self):
        return {"quotes": [self._row_view(x) for g in self.groups for x in g["rows"]]}

    # ---------- 三态判定 ----------
    def _board_for(self, source, symbol):
        for b in self.svc.state.list_boards():
            lock = b.get("source_lock") or {}
            if lock.get("script") == source and (lock.get("identity") or {}).get("symbol") == symbol:
                return b["id"]
        return None

    def _state_of(self, source, symbol, board_id):
        if not board_id:
            return "watch"
        return "visible" if board_id == self.svc.state.current_board_id else "hidden"

    def _row_view(self, row):
        q = self.quotes.get(self.key(row["source"], row["symbol"])) or {}
        board_id = self._board_for(row["source"], row["symbol"])
        return {**row, "price": q.get("price"), "change_pct": q.get("change_pct"),
                "ts": q.get("ts"), "state": self._state_of(row["source"], row["symbol"], board_id),
                "stale": q.get("stale", False),
                "has_board": board_id is not None, "board_id": board_id}

    # ---------- 轮询 ----------
    def _ensure_polling(self):
        with self._lock:
            if self._timer is None:
                self._tick_loop()

    def _tick_loop(self):
        self._timer = threading.Timer(self.poll_s, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self):
        try:
            rows = [x for g in self.groups for x in g["rows"]]
            if rows:
                self._fetch_batch(rows)
                payload = {"rows": [self._row_view(x) for x in rows]}
                self.svc.notify({"type": "quotes_update", **payload})
                for x in rows:
                    if self._row_view(x)["state"] == "visible":
                        q = self.quotes.get(self.key(x["source"], x["symbol"])) or {}
                        bid = self._board_for(x["source"], x["symbol"])
                        self.svc.notify({"type": "quote", "board_id": bid,
                                         "price": q.get("price"), "change_pct": q.get("change_pct"),
                                         "ts": q.get("ts")})
        except Exception as e:  # 轮询永不炸循环
            import logging
            logging.getLogger(__name__).warning("watchlist tick 失败: %s", e)
        finally:
            self._tick_loop()

    # ---------- 性能②③：按源批量 + 可见行去重 ----------
    def _fetch_batch(self, rows):
        import time as _t
        dedup, rest = [], []
        for x in rows:
            bid = self._board_for(x["source"], x["symbol"])
            if bid and bid == self.svc.state.current_board_id:
                board = self.svc.state.get_board(bid)
                tf = getattr(board, "current_timeframe", None) if board else None
                key = self.svc.datasource._key(bid, tf or "")
                st = self.svc.datasource.status.get(key) or {}
                lf = st.get("last_fetch")
                fresh = False
                if lf and tf:
                    try:
                        from datetime import datetime as _dt
                        age = (_dt.now() - _dt.fromisoformat(lf)).total_seconds()
                        fresh = age <= max(2 * self.poll_s, 10)
                    except ValueError:
                        fresh = False
                bars = self.svc.state.get_ohlcv(bid, tf) if tf else []
                if fresh and bars:
                    dedup.append((x, bars[-1]))
                    continue
            rest.append(x)
        # ③ 可见行：K线轮询已拿过价 → 用最新 bar close 合成，省一次 ticker
        for x, bar in dedup:
            self._apply_quote(x, {"price": float(bar["close"]), "ts": int(_t.time() * 1000)},
                              keep_pct=True)
        # ② 按源分组：有 tickers 批量实现=一源一请求；无=回退逐行
        by_src = {}
        for x in rest:
            by_src.setdefault(x["source"], []).append(x)
        for src, group in by_src.items():
            if self.svc.script_engine.has_batch_ticker(src):
                r = self.svc.script_engine.tickers(src, [{"symbol": x["symbol"]} for x in group])
                if not r.get("error"):
                    for x, q in zip(group, r.get("quotes") or []):
                        if q:
                            self._apply_quote(x, q)
                        else:
                            self._mark_fail(x)
                    continue
            list(self._pool.map(self._fetch_one, group))

    def _apply_quote(self, row, q, keep_pct=False):
        k = self.key(row["source"], row["symbol"])
        with self._lock:
            cur = self.quotes.setdefault(k, {"price": None, "change_pct": None, "ts": None,
                                             "state": "watch", "fails": 0, "stale": False})
            cur["price"] = q["price"]
            cur["ts"] = q["ts"]
            if not keep_pct or q.get("change_pct") is not None:
                cur["change_pct"] = q.get("change_pct")
            cur["fails"] = 0
            cur["stale"] = False
            cur["state"] = self._state_of(row["source"], row["symbol"],
                                          self._board_for(row["source"], row["symbol"]))

    def _mark_fail(self, row):
        k = self.key(row["source"], row["symbol"])
        with self._lock:
            q = self.quotes.setdefault(k, {"price": None, "change_pct": None, "ts": None,
                                           "state": "watch", "fails": 0, "stale": False})
            q["fails"] += 1
            if q["fails"] >= 10:
                q["stale"] = True

    def _fetch_one(self, row):
        k = self.key(row["source"], row["symbol"])
        try:
            r = self.svc.script_engine.ticker(row["source"], {"symbol": row["symbol"]})
        except Exception as e:
            r = {"error": f"TICKER_EXCEPTION: {e}"}
        if r.get("error"):
            self._mark_fail(row)
            return
        self._apply_quote(row, r["quote"])

    def _bc_changed(self):
        self.svc.notify({"type": "watchlist_changed", "groups": self.list_watchlist()["groups"]})

    def stop(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
