"""指标目录：内置 75 项（indicator_spec.json）+ 运行时自定义脚本。

内置目录由 tools/gen_indicator_spec.mjs 从 vendored Vela bundle 生成；
自定义脚本（scripts_dir/indicator/*.py，source=custom）在请求时合并进来，
统一归入「自定义」分类，不参与内置 7 类的策展（用户裁决 2026-10-20）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_SPEC: Optional[dict] = None
_BY_SCRIPT: Optional[dict] = None

CUSTOM_GROUP = {"id": "custom", "label": "自定义", "label_en": "Custom"}


def load() -> dict:
    global _SPEC, _BY_SCRIPT
    if _SPEC is None:
        path = Path(__file__).resolve().parent.parent / "resources" / "indicator_spec.json"
        _SPEC = json.loads(path.read_text(encoding="utf-8"))
        _BY_SCRIPT = {m["script"]: m for m in _SPEC["indicators"]}
    return _SPEC


def by_script(script: str) -> Optional[dict]:
    load()
    return (_BY_SCRIPT or {}).get(script)


def defaults(script: str) -> dict:
    meta = by_script(script)
    if not meta:
        return {}
    return {i["key"]: i.get("defval") for i in meta.get("inputs", [])}


def _input_type(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, list):
        return "list"
    return "string"


def _infer_inputs(params: dict) -> list:
    """自定义脚本没有 inputs schema，从 PARAMS 字面量推断设置面板控件类型。"""
    out = []
    for k, v in (params or {}).items():
        out.append({
            "key": k, "title": k, "type": _input_type(v),
            "defval": "" if v is None else v,
        })
    return out


def catalog(engine=None) -> dict:
    """内置目录 + 自定义脚本合并视图。

    engine=ScriptEngine 时把 custom 指标并入：
    - 新脚本 → group='custom'，overlay 由 SUBPLOT 反推，inputs 由 PARAMS 推断；
    - 与内置同 id（shadow）→ 复用内置卡片，source 标 custom/shadowed=true，不重复出卡。
    没有自定义脚本时不追加空分类。
    """
    spec = load()
    if engine is None:
        return spec

    builtin = {m["script"]: m for m in spec["indicators"]}
    indicators = [{**m, "source": "builtin"} for m in spec["indicators"]]
    custom_entries = []
    for sc in engine.list_scripts():
        if sc.get("kind") != "indicator" or sc.get("source") != "custom":
            continue
        sid = sc["id"]
        if sid in builtin:
            for i, m in enumerate(indicators):
                if m["script"] == sid:
                    indicators[i] = {**m, "source": "custom", "shadowed": True}
                    break
            continue
        meta = engine.metadata(sid) or {}
        stem = sid.split("/")[-1]
        custom_entries.append({
            "type": stem,
            "script": sid,
            "title": sc.get("display") or stem,
            "short": sc.get("display") or stem,
            "title_zh": sc.get("display") or stem,
            "desc": sc.get("desc") or "",
            "group": "custom",
            "overlay": not bool(meta.get("subplot")),
            "inputs": _infer_inputs(sc.get("params") or {}),
            "source": "custom",
        })

    groups = list(spec["groups"]) + [CUSTOM_GROUP]
    if not custom_entries:
        return {**spec, "groups": groups, "indicators": indicators, "custom_count": 0}
    custom_entries.sort(key=lambda m: m["title"].lower())
    return {**spec, "groups": groups,
            "indicators": indicators + custom_entries,
            "custom_count": len(custom_entries)}
