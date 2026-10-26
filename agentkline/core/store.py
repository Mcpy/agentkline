"""
AgentKline v0.6.3 - 持久化现场库（SQLite / WAL）

设计要点（定稿见 docs/0.6.3-持久化方案.md）：
- 存“现场”不存“行情”：画板/周期配置/指标实例/画线/结果/雷达落盘，K 线与物化缓存重启重取重算；
- 一次用户操作 = 一个事务；结果 = 摘要行 + 净值分块 + 交易产物一次写入（要么整条，要么没有）；
- 启动 quick_check，损坏即改名旁路（state.db.corrupt-<ts>），空库起，服务不被一块坏盘拖死；
- 迁移用 PRAGMA user_version，只前进；高于程序版本时拒绝启动，防降级写坏库。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from .results import summarize

logger = logging.getLogger("agentkline.store")

SCHEMA_VERSION = 1
EQUITY_CHUNK = 500      # 净值分块：每块 500 点 [[ts,value],…]
EVENTS_KEEP = 5000      # 事件账本上限（超出裁旧）

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS meta (
           key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS boards (
           id TEXT PRIMARY KEY, name TEXT NOT NULL, intervals TEXT NOT NULL,
           current_tf TEXT, source_lock TEXT,
           created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS timeframes (
           board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
           tf TEXT NOT NULL, symbol TEXT, subplots TEXT,
           PRIMARY KEY (board_id, tf))""",
    """CREATE TABLE IF NOT EXISTS indicators (
           board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
           inst_id TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL,
           PRIMARY KEY (board_id, inst_id))""",
    """CREATE TABLE IF NOT EXISTS drawings (
           board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
           id TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL,
           PRIMARY KEY (board_id, id))""",
    """CREATE TABLE IF NOT EXISTS results (
           result_id TEXT PRIMARY KEY,
           board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
           tf TEXT, kind TEXT NOT NULL DEFAULT 'backtest', status TEXT,
           summary TEXT NOT NULL, products TEXT, created_at INTEGER NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS results_board ON results(board_id, created_at DESC)""",
    """CREATE TABLE IF NOT EXISTS result_equity (
           result_id TEXT NOT NULL REFERENCES results(result_id) ON DELETE CASCADE,
           chunk INTEGER NOT NULL, points TEXT NOT NULL,
           PRIMARY KEY (result_id, chunk))""",
    """CREATE TABLE IF NOT EXISTS wl_groups (
           id TEXT PRIMARY KEY, name TEXT NOT NULL, sort INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS wl_rows (
           source TEXT NOT NULL, symbol TEXT NOT NULL,
           group_id TEXT NOT NULL REFERENCES wl_groups(id) ON DELETE CASCADE,
           sort INTEGER NOT NULL, PRIMARY KEY (source, symbol))""",
    """CREATE TABLE IF NOT EXISTS events (
           id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,
           board_id TEXT, kind TEXT NOT NULL, payload TEXT)""",
)


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _loads(raw, default=None):
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


class Store:
    """现场库读写口（单连接 + 进程内锁；服务是单进程双端口）。"""

    def __init__(self, path, app_version: str = ""):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._event_writes = 0
        self._open(app_version)

    # ---------- 打开 / 迁移 / 损坏旁路 ----------
    def _open(self, app_version: str) -> None:
        reason = ""
        for _ in (0, 1):   # 第一次失败 → 隔离坏库 → 第二次在新库上重试
            conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA busy_timeout=5000")
                verdict = str(conn.execute("PRAGMA quick_check").fetchone()[0]).lower()
                if verdict == "ok":
                    self._conn = conn
                    self._migrate(app_version)
                    if reason:
                        self.log_event("db_recovered", {"quarantined": reason})
                    return
                reason = f"quick_check={verdict}"
            except sqlite3.DatabaseError as exc:
                reason = f"{type(exc).__name__}: {exc}"
            try:
                conn.close()
            except Exception:
                pass
            self._quarantine()
        raise sqlite3.DatabaseError(f"无法建立现场库 {self.path}: {reason}")

    def _quarantine(self) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(self.path) + suffix)
            if not src.exists():
                continue
            try:
                src.replace(Path(str(target) + suffix))
            except OSError:
                logger.error("现场库隔离失败: %s", src)
        logger.error("现场库损坏，已改名旁路: %s -> %s；空库启动",
                     self.path.name, target.name)

    def _migrate(self, app_version: str) -> None:
        with self._lock:
            current = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    f"现场库版本 {current} 高于当前程序 {SCHEMA_VERSION}，拒绝降级写入")
            if current < SCHEMA_VERSION:
                with self._conn:
                    for ddl in _SCHEMA:
                        self._conn.execute(ddl)
                    self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                logger.info("现场库建表完成 v%s: %s", SCHEMA_VERSION, self.path)
            if app_version:
                self.set_meta("app_version", app_version)

    def close(self) -> None:
        with self._lock:
            if self._conn is None:
                return
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            try:
                self._conn.close()
            finally:
                self._conn = None

    # ---------- 低层 ----------
    def _write(self, sql: str, args=()) -> None:
        with self._lock:
            if self._conn is None:
                raise sqlite3.ProgrammingError("现场库已关闭")
            with self._conn:
                self._conn.execute(sql, args)

    def _rows(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self._lock:
            if self._conn is None:
                raise sqlite3.ProgrammingError("现场库已关闭")
            return self._conn.execute(sql, args).fetchall()

    # ---------- meta ----------
    def get_meta(self, key: str, default=None):
        rows = self._rows("SELECT value FROM meta WHERE key=?", (key,))
        return rows[0]["value"] if rows else default

    def set_meta(self, key: str, value) -> None:
        self._write(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, "" if value is None else str(value)))

    # ---------- 画板 ----------
    def upsert_board(self, board: dict) -> None:
        now = _iso()
        lock = board.get("source_lock")
        self._write(
            """INSERT INTO boards(id,name,intervals,current_tf,source_lock,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, intervals=excluded.intervals,
                 current_tf=excluded.current_tf, source_lock=excluded.source_lock,
                 updated_at=excluded.updated_at""",
            (board["id"], board["name"], _dumps(board.get("intervals") or []),
             board.get("current_tf"),
             None if lock is None else _dumps(lock),
             board.get("created_at") or now, now))

    def delete_board(self, board_id: str) -> None:
        self._write("DELETE FROM boards WHERE id=?", (board_id,))

    def load_boards(self) -> list[dict]:
        rows = self._rows("SELECT * FROM boards ORDER BY created_at, rowid")
        return [{"id": r["id"], "name": r["name"],
                 "intervals": _loads(r["intervals"], []) or [],
                 "current_tf": r["current_tf"],
                 "source_lock": _loads(r["source_lock"], None),
                 "created_at": r["created_at"]} for r in rows]

    def count_boards(self) -> int:
        return int(self._rows("SELECT COUNT(*) AS n FROM boards")[0]["n"])

    # ---------- 周期 ----------
    def upsert_timeframe(self, board_id: str, tf: str, symbol: str = "",
                         subplots=None) -> None:
        self._write(
            """INSERT INTO timeframes(board_id,tf,symbol,subplots) VALUES(?,?,?,?)
               ON CONFLICT(board_id,tf) DO UPDATE SET
                 symbol=excluded.symbol, subplots=excluded.subplots""",
            (board_id, tf, symbol or "", _dumps(subplots or {})))

    def delete_timeframe(self, board_id: str, tf: str) -> None:
        self._write("DELETE FROM timeframes WHERE board_id=? AND tf=?", (board_id, tf))

    def load_timeframes(self, board_id: str) -> list[dict]:
        rows = self._rows(
            "SELECT tf,symbol,subplots FROM timeframes WHERE board_id=? ORDER BY rowid",
            (board_id,))
        return [{"tf": r["tf"], "symbol": r["symbol"] or "",
                 "subplots": _loads(r["subplots"], {}) or {}} for r in rows]

    # ---------- 指标实例 ----------
    def upsert_indicator(self, board_id: str, inst: dict) -> None:
        self._write(
            """INSERT INTO indicators(board_id,inst_id,payload,updated_at) VALUES(?,?,?,?)
               ON CONFLICT(board_id,inst_id) DO UPDATE SET
                 payload=excluded.payload, updated_at=excluded.updated_at""",
            (board_id, inst["inst_id"], _dumps(inst), _iso()))

    def delete_indicator(self, board_id: str, inst_id: str) -> None:
        self._write("DELETE FROM indicators WHERE board_id=? AND inst_id=?",
                    (board_id, inst_id))

    def load_indicators(self, board_id: str) -> list[dict]:
        rows = self._rows(
            "SELECT payload FROM indicators WHERE board_id=? ORDER BY rowid", (board_id,))
        out = []
        for r in rows:
            inst = _loads(r["payload"], None)
            if isinstance(inst, dict) and inst.get("inst_id"):
                inst.setdefault("visible", True)
                out.append(inst)
        return out

    # ---------- 画线 ----------
    def upsert_drawing(self, board_id: str, drawing: dict) -> None:
        self._write(
            """INSERT INTO drawings(board_id,id,payload,updated_at) VALUES(?,?,?,?)
               ON CONFLICT(board_id,id) DO UPDATE SET
                 payload=excluded.payload, updated_at=excluded.updated_at""",
            (board_id, drawing["id"], _dumps(drawing), _iso()))

    def delete_drawing(self, board_id: str, drawing_id: str) -> None:
        self._write("DELETE FROM drawings WHERE board_id=? AND id=?",
                    (board_id, drawing_id))

    def load_drawings(self, board_id: str) -> list[dict]:
        rows = self._rows(
            "SELECT payload FROM drawings WHERE board_id=? ORDER BY rowid", (board_id,))
        return [d for d in (_loads(r["payload"], None) for r in rows)
                if isinstance(d, dict) and d.get("id")]

    # ---------- 结果 ----------
    def insert_result(self, board_id: str, result: dict) -> None:
        """结果整体一个事务：摘要行 + 净值分块 + 交易产物。"""
        rid = result["result_id"]
        summary = summarize(result)
        products = {"trades": result.get("trades") or [],
                    "fills": result.get("fills") or [],
                    "benchmark": result.get("benchmark")}
        eq = result.get("equity") or {}
        points = list(zip(eq.get("times") or [], eq.get("values") or []))
        chunks = [points[i:i + EQUITY_CHUNK] for i in range(0, len(points), EQUITY_CHUNK)]
        tf = (result.get("data") or {}).get("timeframe")
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """INSERT OR REPLACE INTO results
                       (result_id,board_id,tf,kind,status,summary,products,created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (rid, board_id, tf, "backtest", result.get("status"),
                     _dumps(summary), _dumps(products),
                     int(result.get("created_at") or 0)))
                self._conn.execute("DELETE FROM result_equity WHERE result_id=?", (rid,))
                self._conn.executemany(
                    "INSERT INTO result_equity(result_id,chunk,points) VALUES(?,?,?)",
                    [(rid, i, _dumps(chunk)) for i, chunk in enumerate(chunks)])

    def update_result_summary(self, result_id: str, summary: dict) -> None:
        self._write("UPDATE results SET summary=?, status=? WHERE result_id=?",
                    (_dumps(summary), summary.get("status"), result_id))

    def delete_result(self, result_id: str) -> None:
        self._write("DELETE FROM results WHERE result_id=?", (result_id,))

    def load_result_summaries(self, board_id: str) -> list[dict]:
        rows = self._rows(
            "SELECT summary FROM results WHERE board_id=? ORDER BY created_at DESC",
            (board_id,))
        out = []
        for r in rows:
            s = _loads(r["summary"], None)
            if isinstance(s, dict) and s.get("result_id"):
                out.append(s)
        return out

    def load_equity(self, result_id: str) -> dict:
        rows = self._rows(
            "SELECT points FROM result_equity WHERE result_id=? ORDER BY chunk",
            (result_id,))
        times, values = [], []
        for r in rows:
            for point in _loads(r["points"], []) or []:
                try:
                    times.append(point[0])
                    values.append(point[1])
                except (IndexError, TypeError):
                    continue
        return {"times": times, "values": values}

    def load_result(self, result_id: str) -> Optional[dict]:
        rows = self._rows("SELECT * FROM results WHERE result_id=?", (result_id,))
        if not rows:
            return None
        row = rows[0]
        out = _loads(row["summary"], None)
        if not isinstance(out, dict):
            return None
        # 摘要列里只给列表用的两个派生计数，还原成内存结构时去掉
        out.pop("equity_points", None)
        out.pop("trade_count", None)
        out["equity"] = self.load_equity(result_id)
        products = _loads(row["products"], {}) or {}
        out["trades"] = products.get("trades") or []
        out["fills"] = products.get("fills") or []
        out["benchmark"] = products.get("benchmark")
        return out

    def count_results(self) -> int:
        return int(self._rows("SELECT COUNT(*) AS n FROM results")[0]["n"])

    # ---------- 雷达 ----------
    def save_watchlist(self, groups: list[dict]) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute("DELETE FROM wl_rows")
                self._conn.execute("DELETE FROM wl_groups")
                for gi, group in enumerate(groups or []):
                    self._conn.execute(
                        "INSERT INTO wl_groups(id,name,sort) VALUES(?,?,?)",
                        (group["id"], group["name"], gi))
                    for ri, row in enumerate(group.get("rows") or []):
                        self._conn.execute(
                            "INSERT OR REPLACE INTO wl_rows(source,symbol,group_id,sort) "
                            "VALUES(?,?,?,?)",
                            (row["source"], row["symbol"], group["id"], ri))

    def load_watchlist(self) -> list[dict]:
        out = []
        for g in self._rows("SELECT id,name FROM wl_groups ORDER BY sort"):
            rows = self._rows(
                "SELECT source,symbol FROM wl_rows WHERE group_id=? ORDER BY sort",
                (g["id"],))
            out.append({"id": g["id"], "name": g["name"],
                        "rows": [{"source": r["source"], "symbol": r["symbol"]} for r in rows]})
        return out

    # ---------- 事件账本 ----------
    def log_event(self, kind: str, payload=None, board_id: Optional[str] = None) -> None:
        try:
            self._write(
                "INSERT INTO events(ts,board_id,kind,payload) VALUES(?,?,?,?)",
                (int(time.time() * 1000), board_id, str(kind),
                 None if payload is None else _dumps(payload)))
            self._event_writes += 1
            if self._event_writes % 200 == 0:
                self._write(
                    "DELETE FROM events WHERE id <= "
                    "(SELECT COALESCE(MAX(id),0) FROM events) - ?", (EVENTS_KEEP,))
        except Exception:
            logger.warning("事件写入失败: %s", kind, exc_info=True)

    def recent_events(self, limit: int = 50) -> list[dict]:
        rows = self._rows(
            "SELECT ts,board_id,kind,payload FROM events ORDER BY id DESC LIMIT ?",
            (int(limit),))
        return [{"ts": r["ts"], "board_id": r["board_id"], "kind": r["kind"],
                 "payload": _loads(r["payload"], None)} for r in rows]

    # ---------- 统计 ----------
    def stats(self) -> dict:
        def count(table: str) -> int:
            return int(self._rows(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"])
        return {
            "path": str(self.path),
            "size": self.path.stat().st_size if self.path.exists() else 0,
            "schema": int(self._rows("PRAGMA user_version")[0][0]),
            "boards": count("boards"),
            "timeframes": count("timeframes"),
            "indicators": count("indicators"),
            "drawings": count("drawings"),
            "results": count("results"),
            "result_equity": count("result_equity"),
            "watchlist_rows": count("wl_rows"),
            "events": count("events"),
        }
