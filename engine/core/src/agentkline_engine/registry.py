"""引擎发现：entry point group `agentkline.engines`。"""
from __future__ import annotations

from importlib.metadata import entry_points

from .contract import ENGINE_API, Engine
from .errors import AKError

GROUP = "agentkline.engines"


def discover() -> tuple[dict[str, Engine], dict[str, str]]:
    """返回 (engines, load_errors)。坏插件只记录，不影响其他引擎。"""
    engines: dict[str, Engine] = {}
    errors: dict[str, str] = {}
    try:
        eps = entry_points()
    except Exception as exc:  # pragma: no cover - 元数据损坏
        raise AKError("ENGINE_INTERNAL", f"读取 entry points 失败: {exc}")
    if hasattr(eps, "select"):
        selected = eps.select(group=GROUP)
    else:  # pragma: no cover - Python 3.9 兼容
        selected = eps.get(GROUP, [])
    for ep in selected:
        try:
            obj = ep.load()
            inst = obj() if isinstance(obj, type) else obj
            eid = str(getattr(inst, "id", "") or ep.name)
            engines[eid] = inst
        except Exception as exc:  # noqa: BLE001 - 插件自身问题
            errors[ep.name] = f"{type(exc).__name__}: {exc}"
    return engines, errors


def get_engine(engine_id: str) -> Engine:
    engines, errors = discover()
    if engine_id not in engines:
        available = sorted(engines)
        detail = {"available": available}
        if errors:
            detail["load_errors"] = errors
        raise AKError("ENGINE_NOT_FOUND", f"未找到引擎 {engine_id!r}", detail=detail)
    eng = engines[engine_id]
    api = int(getattr(eng, "api", 0) or 0)
    if api != ENGINE_API:
        raise AKError("API_MISMATCH",
                      f"引擎 {engine_id!r} api={api}，本框架支持 {ENGINE_API}")
    return eng


def list_engines() -> list[dict]:
    engines, errors = discover()
    out = []
    for eid in sorted(engines):
        eng = engines[eid]
        out.append({
            "id": eid,
            "version": str(getattr(eng, "version", "") or ""),
            "api": int(getattr(eng, "api", 0) or 0),
            "caps": dict(getattr(eng, "caps", {}) or {}),
            "assumptions": dict(getattr(eng, "assumptions", {}) or {}),
            "load_error": errors.get(eid),
        })
    return out
