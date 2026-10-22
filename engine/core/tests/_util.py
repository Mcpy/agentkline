"""测试共用工具：合成行情、跑用例、深度比较。"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases"
EXPECTED = CASES / "expected"
ROOT = HERE.parents[2]

sys.path.insert(0, str(ROOT))


def bars_from_closes(closes, start=1_600_000_000_000, step=86_400_000, opens=None):
    """按收盘价序列造 K 线：默认开盘=前收，高低各留 0.5%。"""
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = opens[i] if opens else (prev if i else c)
        out.append({
            "timestamp": start + i * step,
            "open": o,
            "high": max(o, c) * 1.005,
            "low": min(o, c) * 0.995,
            "close": c,
            "volume": 1.0,
        })
        prev = c
    return out


def spec(name: str) -> dict:
    with (CASES / f"{name}.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def build(name: str):
    """按用例名构造 RunRequest（相对路径以 cases 目录为基准）。"""
    from agentkline_engine.cli import build_request
    return build_request(spec(name), base_dir=CASES)


def expected(name: str) -> dict:
    with (EXPECTED / f"{name}.result.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def _cmp(a, b, path="", tol=1e-12, diffs=None):
    diffs = diffs if diffs is not None else []
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            diffs.append(f"{path}: keys {sorted(set(a) ^ set(b))}")
        for k in a:
            if k in b:
                _cmp(a[k], b[k], f"{path}.{k}", tol, diffs)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{path}: len {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            _cmp(x, y, f"{path}[{i}]", tol, diffs)
    elif isinstance(a, float) or isinstance(b, float):
        if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
            diffs.append(f"{path}: {a!r} != {b!r}")
            return
        if not math.isfinite(a) or not math.isfinite(b):
            if a != b:
                diffs.append(f"{path}: {a!r} != {b!r}")
        elif abs(a - b) > tol * max(1.0, abs(a), abs(b)):
            diffs.append(f"{path}: {a!r} != {b!r}")
    else:
        if a != b:
            diffs.append(f"{path}: {a!r} != {b!r}")
    return diffs


def assert_deep_equal(testcase, got, want, tol=1e-12, msg=""):
    diffs = _cmp(got, want, tol=tol)
    if diffs:
        testcase.fail(f"{msg} 结果不一致（{len(diffs)} 处）：\n" + "\n".join(diffs[:12]))
