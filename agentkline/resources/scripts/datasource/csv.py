"""
数据源：本地 CSV 文件（离线）
path 是**操作参数**（不进板锁身份，IDENTITY=[]）：同一 CSV 源可换文件不撞锁
"""
import csv
from datetime import datetime

NAME = "CSV 文件"
DESC = "读取本地 CSV 为 K 线；列名可映射；时间支持毫秒/秒/ISO 字符串"
PARAMS = {"path": "", "time_col": "timestamp", "open_col": "open",
          "high_col": "high", "low_col": "low", "close_col": "close",
          "volume_col": "volume"}
CAPS = {"backfill": False, "symbols": False, "ticker": False}
IDENTITY = []


def _parse_time(v):
    """毫秒/秒时间戳或 ISO 字符串 → 毫秒"""
    if isinstance(v, (int, float)):
        n = float(v)
    else:
        s = str(v).strip()
        try:
            n = float(s)
        except ValueError:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
    if n < 1e11:  # 秒 → 毫秒（与前端单位自适应同姿态）
        n *= 1000
    return int(n)


def main(params: dict) -> list:
    path = params.get("path", "")
    if not path:
        raise ValueError("params.path 必填（CSV 文件路径）")
    tc = params.get("time_col", "timestamp")
    cols = {k: params.get(f"{k}_col", k) for k in ("open", "high", "low", "close", "volume")}

    bars = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not row.get(tc):
                continue
            bars.append({
                "timestamp": _parse_time(row[tc]),
                "open": float(row[cols["open"]]),
                "high": float(row[cols["high"]]),
                "low": float(row[cols["low"]]),
                "close": float(row[cols["close"]]),
                "volume": float(row[cols["volume"]] or 0),
            })
    bars.sort(key=lambda b: b["timestamp"])
    return bars
