"""生成确定性测试行情（commit 的 CSV 由本脚本产出，别手改）。"""
from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases"


def _walk(n: int, start: float, seed: int, drift: float = 0.0004, vol: float = 0.02):
    rnd = random.Random(seed)
    price = start
    out = []
    for _ in range(n):
        o = price
        c = max(0.01, o * math.exp(rnd.gauss(drift, vol)))
        h = max(o, c) * (1 + abs(rnd.gauss(0, vol / 3)))
        l = min(o, c) * (1 - abs(rnd.gauss(0, vol / 3)))
        v = round(abs(rnd.gauss(1000, 250)), 3)
        out.append((o, h, l, c, v))
        price = c
    return out


def write_csv(path: Path, rows, start: datetime, step: timedelta, skip_weekend: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        ts = start
        for r in rows:
            if skip_weekend:
                while ts.weekday() >= 5:
                    ts += step
            w.writerow([int(ts.timestamp() * 1000), *[f"{x:.8f}" if i < 4 else f"{x:.4f}"
                                                     for i, x in enumerate(r)]])
            ts += step


def main():
    base = datetime(2019, 9, 8, tzinfo=timezone.utc)
    write_csv(CASES / "btc_1d_200.csv", _walk(200, 10000.0, 42), base, timedelta(days=1))
    # 股票日历：跳过周末，用来验证观测密度年化 ~252
    write_csv(CASES / "stock_1d_500.csv", _walk(500, 100.0, 7, vol=0.01), base,
              timedelta(days=1), skip_weekend=True)
    # 周线：用于短样本回退
    write_csv(CASES / "weekly_20.csv", _walk(20, 50.0, 3, vol=0.05), base, timedelta(days=7))
    print("cases written to", CASES)


if __name__ == "__main__":
    main()
