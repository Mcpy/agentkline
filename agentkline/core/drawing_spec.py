"""画线工具规格（Vela 0.8.4 注册表快照）。

由 `tools/gen_drawing_spec.mjs` 从 vendored bundle 运行时注册表生成：
79 种类型 / 7 个工具栏分组，含每种类型的锚点数量与角色。
服务端用同一份数据做两件事：MCP 清单（list_drawing_tools）与落库前校验。
升级 Vela 后重跑生成脚本即可（勿手改 JSON）。
"""
import json
from pathlib import Path

_SPEC_PATH = Path(__file__).resolve().parent.parent / "resources" / "drawing_spec.json"
_SPEC = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))

VELA = _SPEC["vela"]
GROUPS = _SPEC["groups"]
TOOLS = {t["type"]: t for t in _SPEC["tools"]}
ORDER = [t["type"] for t in _SPEC["tools"]]

_ALIAS = {
    "line": "lines", "lines": "lines",
    "fib": "fibonacci", "fibonacci": "fibonacci",
    "pattern": "patterns", "patterns": "patterns",
    "measure": "measurements", "measurement": "measurements", "measurements": "measurements",
    "shape": "shapes", "shapes": "shapes",
    "text": "text",
    "icon": "icons", "icons": "icons",
}


def group_of(category):
    return _ALIAS.get((category or "").strip().lower())


def summary():
    """7 组概览（不展开 79 条，给模型一个目录）。"""
    return {
        "vela": VELA,
        "groups": [
            {"id": g["id"], "label": g["label"], "count": len(g["tools"]),
             "sections": [s["label"] for s in g["sections"]]}
            for g in GROUPS
        ],
        "usage": "调 list_drawing_tools(category=...) 取某组工具与锚点要求；再 draw_drawing(type, anchors)。",
    }


def list_tools(category=None, detail=False):
    """按组列工具。detail=False 只给 type/label/锚点数量/放置方式（省 token）。"""
    gid = group_of(category) if category else None
    if category and not gid:
        return {"error": f"UNKNOWN_CATEGORY: {category}",
                "categories": [g["id"] for g in GROUPS]}
    rows = []
    for t in _SPEC["tools"]:
        if gid and t["group"] != gid:
            continue
        row = {
            "type": t["type"], "label": t["label"], "group": t["group"],
            "section": t["section"], "placement": t["placement"],
            "anchors": {"min": t["anchors"]["min"], "max": t["anchors"]["max"]},
        }
        if detail:
            row["anchors"]["slots"] = t["anchors"]["slots"]
            row["coversSeries"] = t["covers"]
            if t["hint"]:
                row["hint"] = t["hint"]
        rows.append(row)
    out = {"vela": VELA, "category": gid, "count": len(rows), "tools": rows}
    if not gid:
        out["groups"] = [{"id": g["id"], "label": g["label"], "count": len(g["tools"])} for g in GROUPS]
    return out


def validate(type_, anchors):
    """返回 (ok, message)。只校验类型存在与锚点数量；几何由前端 Vela 决定。"""
    meta = TOOLS.get(type_)
    if not meta:
        return False, (f"UNKNOWN_DRAWING_TYPE: {type_}. "
                       f"可用类型见 list_drawing_tools(category=...)（共 {len(TOOLS)} 种）")
    lo, hi = meta["anchors"]["min"], meta["anchors"]["max"]
    n = len(anchors or [])
    if n < lo or (hi and n > hi):
        need = f"{lo}" if lo == hi else f"{lo}-{hi}"
        return False, f"BAD_ANCHORS: {type_} 需要 {need} 个锚点，收到 {n} 个（slots={meta['anchors']['slots']}）"
    return True, ""
