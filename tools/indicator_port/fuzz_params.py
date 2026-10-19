#!/usr/bin/env python3
"""v0.5.3 指标参数健壮性抽查（发布前）：每个研究取若干合法参数变体，确保不抛异常、
线长与 bars 对齐、值只含 float/None。不校验数值正确性（golden 已覆盖默认参数）。

用法: node tools/indicator_port/gen_golden.mjs && .venv/bin/python tools/indicator_port/fuzz_params.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agentkline.indicators import registry  # noqa: E402

SPEC = json.loads((ROOT / "agentkline/resources/indicator_spec.json").read_text())
BARS = json.loads((ROOT / "tools/indicator_port/golden.json").read_text())["bars"]
for b in BARS:
    b["timestamp"] = b["time"]
N = len(BARS)


def variants(inputs):
    out = [{}]
    for inp in inputs:
        key, typ = inp["key"], inp["type"]
        base = inp.get("defval")
        vals = []
        if typ in ("int", "float"):
            lo = inp.get("min", 0)
            vals = [lo, (lo + base) / 2 if base else lo + 1, base * 2 if base else lo + 2, 50]
        elif typ == "bool":
            vals = [not base]
        elif typ == "string" and inp.get("options"):
            vals = [o for o in inp["options"][:2]]
        for v in vals:
            if typ in ("int", "float"):
                if inp.get("max") is not None and v > inp["max"]:
                    continue
                if typ == "int":
                    v = int(v)
                if v == base:
                    continue
            out.append({key: v})
    return out[:8]


def check(t, params):
    fn = registry.STUDIES[t]
    out = fn(params, BARS)
    for ln in out.get("lines") or []:
        vals = ln.get("values") or []
        if len(vals) != N:
            return f"line {ln.get('name')} len {len(vals)} != {N}"
        for v in vals:
            if v is not None and not isinstance(v, (int, float)):
                return f"line {ln.get('name')} non-numeric {v!r}"
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return f"line {ln.get('name')} nan/inf"
    return None


def main() -> int:
    bad = []
    tried = 0
    for meta in SPEC["indicators"]:
        t = meta["type"]
        if t == "kdj":
            continue
        for params in variants(meta["inputs"]):
            tried += 1
            try:
                err = check(t, params)
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {e}"
            if err:
                bad.append((t, params, err))
    print(f"variants={tried} failures={len(bad)}")
    for t, p, e in bad[:40]:
        print(f"  {t} {p}: {e}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
