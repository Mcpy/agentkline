#!/usr/bin/env python3
"""v0.5.3 指标目录一致性检查（发布门前置）。

校验三层是否同源：
  1. indicator_spec.json ↔ 内置脚本 wrapper（存在性 / NAME / PARAMS / SUBPLOT）
  2. indicator_spec.json ↔ Python registry（74 个 Vela 类型，KDJ 除外）
  3. generated visual spec ↔ Python 实际线名（fills 两端、levels/zones 的阈值键）

用法: node tools/indicator_port/gen_golden.mjs && .venv/bin/python tools/indicator_port/check_catalog.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agentkline.core.script_engine import ScriptEngine  # noqa: E402
from agentkline.indicators import registry  # noqa: E402

SPEC = json.loads((ROOT / "agentkline/resources/indicator_spec.json").read_text())
BARS = json.loads((ROOT / "tools/indicator_port/golden.json").read_text())["bars"]
for b in BARS:
    b["timestamp"] = b["time"]

VIS_JS = (ROOT / "frontend/src/indicator_visuals.js").read_text()
VIS = json.loads(VIS_JS[VIS_JS.index("GENERATED_SPEC = ") + len("GENERATED_SPEC = "):].strip().rstrip(";"))


def main() -> int:
    problems: list[str] = []
    engine = ScriptEngine(str(ROOT / "scripts"))
    for meta in SPEC["indicators"]:
        t, script = meta["type"], meta["script"]
        defaults = {i["key"]: i["defval"] for i in meta["inputs"]}
        sm = engine.metadata(script)
        if sm.get("error"):
            problems.append(f"{t}: script missing ({script})")
            continue
        if sm.get("name") != meta["short"]:
            problems.append(f"{t}: NAME {sm.get('name')!r} != {meta['short']!r}")
        if sm.get("params") != defaults:
            problems.append(f"{t}: PARAMS {sm.get('params')} != {defaults}")
        want_sub = not meta["overlay"]
        if bool(sm.get("subplot")) != want_sub:
            problems.append(f"{t}: SUBPLOT {sm.get('subplot')} != {want_sub}")
        if t != "kdj" and t not in registry.STUDIES:
            problems.append(f"{t}: registry missing")
        if t != "kdj":
            out = registry.run(t, {}, BARS)
            names = {ln["name"] for ln in out.get("lines") or []}
            v = VIS.get(script) or {}
            for f in v.get("fills") or []:
                if f["from"] not in names or f["to"] not in names:
                    problems.append(f"{t}: fill {f['from']}->{f['to']} not in {sorted(names)}")
            th = set((v.get("thresholds") or {}).keys()) | set((v.get("axis") or {}).keys())
            for lv in v.get("levels") or []:
                if isinstance(lv.get("at"), str) and lv["at"] not in th:
                    problems.append(f"{t}: level key {lv['at']} has no threshold")
            for z in v.get("zones") or []:
                for end in (z["from"], z["to"]):
                    if isinstance(end, str) and end not in th:
                        problems.append(f"{t}: zone key {end} has no threshold")

    print(f"catalog={len(SPEC['indicators'])} scripts={len(engine.list_scripts())} "
          f"registry={len(registry.STUDIES)} problems={len(problems)}")
    for p in problems:
        print("  -", p)
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
