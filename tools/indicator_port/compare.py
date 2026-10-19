#!/usr/bin/env python3
"""Vela golden ↔ Python 指标移植对比（开发期工具）。

用法:
  .venv/bin/python tools/indicator_port/compare.py                # 全部
  .venv/bin/python tools/indicator_port/compare.py --group band
  .venv/bin/python tools/indicator_port/compare.py --types sma,rsi --verbose
  .venv/bin/python tools/indicator_port/compare.py --types supertrend --dump

判定：golden 中「可见」的 plot（非全隐藏 anchor / 非全透明）必须在 Python 输出里有同名 line，
逐值 allclose；Python 多出的 line 只告警。levels/markers/polylines 若 Python 提供则比对。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agentkline.indicators import registry  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden.json"
RTOL = 1e-6
ATOL = 1e-6


def _hidden(plot: dict) -> bool:
    disp = plot.get("display") or {}
    if disp and disp.get("pane") is False and disp.get("legend") is False and disp.get("dataWindow") is False:
        return True
    color = str(plot.get("color") or "")
    if len(color) == 9 and color.endswith("00"):
        return True
    return False


def _cmp_values(expected: list, actual: list, max_detail: int = 4) -> list[str]:
    problems: list[str] = []
    if len(expected) != len(actual):
        return [f"length {len(actual)} != expected {len(expected)}"]
    bad = 0
    for i, (e, a) in enumerate(zip(expected, actual)):
        if e is None or (isinstance(e, float) and math.isnan(e)):
            if a is not None:
                bad += 1
                if bad <= max_detail:
                    problems.append(f"[{i}] expected None got {a!r}")
            continue
        if a is None:
            bad += 1
            if bad <= max_detail:
                problems.append(f"[{i}] expected {e!r} got None")
            continue
        if not math.isclose(float(e), float(a), rel_tol=RTOL, abs_tol=ATOL):
            bad += 1
            if bad <= max_detail:
                problems.append(f"[{i}] expected {e!r} got {a!r}")
    if bad > max_detail:
        problems.append(f"… {bad} mismatches total")
    return problems


def compare_type(study_type: str, golden: dict, verbose: bool = False, dump: bool = False) -> dict:
    ref = golden["results"][study_type]
    inputs = ref["inputs"]
    bars = golden["bars"]
    try:
        out = registry.run(study_type, inputs, bars)
    except Exception as e:  # noqa: BLE001
        return {"type": study_type, "ok": False, "error": f"{type(e).__name__}: {e}"}
    if out.get("error"):
        return {"type": study_type, "ok": False, "error": out["error"]}

    lines = {ln.get("name"): ln.get("values") for ln in out.get("lines") or []}
    problems: list[str] = []
    expected_visible = [p for p in ref["plots"] if not _hidden(p)]
    for plot in expected_visible:
        title = plot["title"]
        if title not in lines:
            problems.append(f"missing line {title!r}")
            continue
        problems.extend(f"{title}{p}" for p in _cmp_values(plot["values"], lines[title]))
    extra = [n for n in lines if n not in {p["title"] for p in expected_visible}]
    if extra and verbose:
        print(f"  note: extra lines {extra}")

    # 结构化输出（levels/markers/polylines）：Python 提供才比对
    if ref.get("levels") and out.get("levels") is not None:
        gp = [round(float(x["price"]), 8) for x in ref["levels"]]
        pp = [round(float(x["price"]), 8) for x in out["levels"]]
        if gp != pp:
            problems.append(f"levels {pp} != {gp}")
    if ref.get("markers") and out.get("markers") is not None:
        if len(ref["markers"]) != len(out["markers"]):
            problems.append(f"markers count {len(out['markers'])} != {len(ref['markers'])}")
        else:
            for i, (g, p) in enumerate(zip(ref["markers"], out["markers"])):
                if g.get("time") != p.get("time") or g.get("position") != p.get("position"):
                    problems.append(f"marker[{i}] {p} != {g}")
                    break
    if ref.get("polylines") and out.get("polylines") is not None:
        if len(ref["polylines"]) != len(out["polylines"]):
            problems.append(f"polylines count {len(out['polylines'])} != {len(ref['polylines'])}")
        else:
            for i, (g, p) in enumerate(zip(ref["polylines"], out["polylines"])):
                gp = [(pt.get("x"), pt.get("price")) for pt in g.get("points") or []]
                pp = [(pt.get("x"), pt.get("price")) for pt in p.get("points") or []]
                if gp != pp:
                    problems.append(f"polyline[{i}] mismatch ({len(pp)} vs {len(gp)} pts)")
                    break

    if dump:
        print(json.dumps({"golden_visible": [p["title"] for p in expected_visible],
                          "python_lines": list(lines),
                          "python_levels": out.get("levels")}, ensure_ascii=False, indent=1))
    return {"type": study_type, "ok": not problems, "problems": problems}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--types", help="逗号分隔 type")
    ap.add_argument("--group", help="按目录分类过滤")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    golden = json.loads(GOLDEN.read_text())
    spec = json.loads((ROOT / "agentkline/resources/indicator_spec.json").read_text())
    group_of = {m["type"]: m["group"] for m in spec["indicators"]}

    wanted = [t for t in golden["results"] if t != "kdj"]
    if args.types:
        wanted = [t.strip() for t in args.types.split(",") if t.strip()]
    if args.group:
        wanted = [t for t in wanted if group_of.get(t) == args.group]

    results = []
    for t in wanted:
        r = compare_type(t, golden, args.verbose, args.dump)
        results.append(r)
        if not args.quiet:
            if r["ok"]:
                print(f"PASS {t}")
            else:
                print(f"FAIL {t}: {r.get('error') or ''}")
                for p in r.get("problems") or []:
                    print(f"     {p}")

    passed = sum(1 for r in results if r["ok"])
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
