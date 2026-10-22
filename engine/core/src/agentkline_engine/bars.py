"""K 线输入层：时间戳归一、字段归一、排序去重、CSV/JSON 读取。

策略与撮合只认 `{"timestamp","open","high","low","close","volume"}`（ms 整数时间戳）。
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from .errors import AKError

_FIELDS = ("timestamp", "open", "high", "low", "close", "volume")
_TS_ALIASES = ("timestamp", "time", "ts", "date", "t")
_ALIASES = {
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c"),
    "volume": ("volume", "vol", "v"),
}
_MS = 10 ** 11     # >= 这个量级视为毫秒
_SEC = 10 ** 8     # 介于 SEC 与 MS 之间视为秒


def to_ms(v) -> int | None:
    """秒/毫秒/ISO 字符串 → 毫秒整数。无法识别返回 None。"""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        dt = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        n = float(v)
        if n != n or n in (float("inf"), float("-inf")):
            return None
        a = abs(n)
        if a >= _MS:
            return int(n)
        if a >= _SEC:
            return int(n * 1000)
        return int(n)
    s = str(v).strip()
    if not s:
        return None
    try:
        n = float(s)
    except ValueError:
        pass
    else:
        return to_ms(n)
    txt = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            return None
    return to_ms(dt)


def _num(v, field_name: str, idx: int) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise AKError("BARS_INVALID", f"第 {idx} 根 {field_name} 不是数字: {v!r}")
    if f != f or f in (float("inf"), float("-inf")):
        raise AKError("BARS_INVALID", f"第 {idx} 根 {field_name} 不是有限数")
    return f


def _pick(item: dict, names) -> object:
    for k in names:
        if k in item and item[k] is not None and item[k] != "":
            return item[k]
    return None


def normalize_bars(raw, *, source: str = "bars") -> tuple[list[dict], list[str]]:
    """归一化 bars。返回 (bars, warnings)。"""
    if not isinstance(raw, (list, tuple)):
        raise AKError("BARS_INVALID", f"{source} 必须是数组")
    if not raw:
        raise AKError("BARS_INVALID", f"{source} 不能为空")
    warnings: list[str] = []
    out: list[dict] = []
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            ts_raw = _pick(item, _TS_ALIASES)
            vals = {f: _pick(item, _ALIASES[f]) for f in ("open", "high", "low", "close", "volume")}
        elif isinstance(item, (list, tuple)) and len(item) >= 5:
            ts_raw = item[0]
            vals = {"open": item[1], "high": item[2], "low": item[3],
                    "close": item[4], "volume": item[5] if len(item) > 5 else 0}
        else:
            raise AKError("BARS_INVALID", f"第 {i} 根 K 线格式不支持（需要对象或 6 元数组）")
        ts = to_ms(ts_raw)
        if ts is None:
            raise AKError("BARS_INVALID", f"第 {i} 根时间戳无法识别: {ts_raw!r}")
        bar = {"timestamp": ts}
        for f in ("open", "high", "low", "close"):
            bar[f] = _num(vals[f], f, i)
        bar["volume"] = _num(vals["volume"] if vals["volume"] is not None else 0, "volume", i)
        if bar["high"] < bar["low"]:
            raise AKError("BARS_INVALID", f"第 {i} 根 high < low")
        if bar["close"] <= 0 or bar["low"] <= 0:
            raise AKError("BARS_INVALID", f"第 {i} 根价格必须 > 0")
        if bar["volume"] < 0:
            raise AKError("BARS_INVALID", f"第 {i} 根 volume 不能为负")
        out.append(bar)

    out.sort(key=lambda b: b["timestamp"])
    deduped: list[dict] = []
    dup = 0
    for b in out:
        if deduped and b["timestamp"] == deduped[-1]["timestamp"]:
            deduped[-1] = b
            dup += 1
        else:
            deduped.append(b)
    if dup:
        warnings.append(f"bars_deduped={dup}")
    return deduped, warnings


def bars_meta(bars: list[dict], timeframe: str = "") -> dict:
    if not bars:
        return {"count": 0, "from": None, "to": None, "timeframe": timeframe}
    return {
        "count": len(bars),
        "from": bars[0]["timestamp"],
        "to": bars[-1]["timestamp"],
        "timeframe": timeframe,
    }


# ============================ 读取 ============================

def _open_text(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise AKError("BARS_INVALID", f"行情文件不存在: {path}")
    return p.read_text(encoding="utf-8-sig")


def read_csv(path: str) -> list[dict]:
    text = _open_text(path)
    rows = list(csv.reader(text.splitlines()))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise AKError("BARS_INVALID", f"CSV 为空: {path}")
    header = [c.strip().lower() for c in rows[0]]
    has_header = any(h in _TS_ALIASES for h in header) or "open" in header
    if has_header:
        cols = {h: i for i, h in enumerate(header)}
        ts_i = next((cols[h] for h in _TS_ALIASES if h in cols), None)
        if ts_i is None:
            raise AKError("BARS_INVALID", "CSV 缺少时间列（timestamp/time/date）")
        idx = {"timestamp": ts_i}
        for f in ("open", "high", "low", "close", "volume"):
            idx[f] = next((cols[a] for a in _ALIASES[f] if a in cols), None)
            if idx[f] is None and f != "volume":
                raise AKError("BARS_INVALID", f"CSV 缺少 {f} 列")
        body = rows[1:]
        items = []
        for r in body:
            row = {}
            for f, i in idx.items():
                row[f] = r[i] if i is not None and i < len(r) else None
            items.append(row)
    else:
        items = [{"timestamp": r[0], "open": r[1], "high": r[2], "low": r[3],
                  "close": r[4], "volume": r[5] if len(r) > 5 else 0} for r in rows]
    bars, warnings = normalize_bars(items, source=path)
    return bars


def read_json(path: str) -> list[dict]:
    text = _open_text(path)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AKError("BARS_INVALID", f"JSON 解析失败: {exc}")
    if isinstance(payload, dict):
        payload = payload.get("bars") or payload.get("data") or payload.get("ohlcv")
    if not isinstance(payload, list):
        raise AKError("BARS_INVALID", "JSON 需要 bars 数组")
    bars, _ = normalize_bars(payload, source=path)
    return bars


def load_bars(src) -> list[dict]:
    """bars 来源：inline 数组 或 {"path":..., "format":"csv|json"}。"""
    if isinstance(src, (list, tuple)):
        bars, _ = normalize_bars(src)
        return bars
    if isinstance(src, dict):
        path = src.get("path")
        if not path:
            raise AKError("BARS_INVALID", "bars 对象需要 path")
        fmt = str(src.get("format") or Path(path).suffix.lstrip(".") or "json").lower()
        if fmt in ("csv", "txt", "tsv"):
            return read_csv(path)
        if fmt in ("json", "jsonl"):
            return read_json(path)
        raise AKError("BARS_INVALID", f"不支持的行情格式: {fmt}")
    raise AKError("BARS_INVALID", "bars 需要数组或 {path,format}")
