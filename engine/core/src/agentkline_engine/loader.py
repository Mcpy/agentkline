"""策略加载：AST 静态校验 + 独立命名空间编译执行。

AST 校验是纯检查（不执行用户代码），供 `save_script` / `validate-strategy` 复用；
`load_strategy` 在校验通过后编译执行，只读取声明与 `main`。
"""
from __future__ import annotations

import ast
import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import AKError

DECLS = ("STRATEGY_MODE", "NAME", "DESC", "WARMUP", "PARAMS",
         "PARAM_META", "PROTECTION", "BARS_PER_YEAR")
REQUIRED_DECLS = ("STRATEGY_MODE", "NAME", "WARMUP", "PARAMS")
_PROTECTION_KEYS = ("stop_loss_pct", "take_profit_pct")
_PARAM_META_KEYS = ("type", "min", "max", "step", "label", "options", "description")
_PARAM_TYPES = ("int", "float", "bool", "str")
_SCALARS = (str, int, float, bool, type(None))


@dataclass
class Strategy:
    name: str
    desc: str
    mode: str
    warmup: int
    params: dict
    param_meta: dict
    protection: dict
    bars_per_year: float | None
    main: Callable
    source: str
    source_sha256: str

    def defaults(self) -> dict:
        return dict(self.params)

    def resolved(self, overrides: dict | None) -> dict:
        return resolve_params(self, overrides or {})


@dataclass
class _Inspect:
    decls: dict = field(default_factory=dict)
    main_node: ast.FunctionDef | None = None
    errors: list = field(default_factory=list)

    def err(self, code: str, message: str) -> None:
        self.errors.append({"code": code, "message": message})


def _literal(node: ast.AST, name: str, ins: _Inspect):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        ins.err("STRATEGY_INVALID", f"{name} 必须是字面量（不能是表达式或函数调用）")
        return _MISSING


_MISSING = object()


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _check_scalar(v) -> bool:
    if isinstance(v, float) and not math.isfinite(v):
        return False
    return isinstance(v, _SCALARS)


def _inspect(source: str) -> _Inspect:
    ins = _Inspect()
    if not isinstance(source, str) or not source.strip():
        ins.err("STRATEGY_SOURCE_EMPTY", "策略源码为空")
        return ins
    try:
        tree = ast.parse(source, filename="<strategy>")
    except SyntaxError as exc:
        ins.err("STRATEGY_INVALID", f"语法错误：第 {exc.lineno} 行 {exc.msg}")
        return ins

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            ins.main_node = node
        elif isinstance(node, ast.AsyncFunctionDef) and node.name == "main":
            ins.err("STRATEGY_INVALID", "main 不能是 async 函数")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in DECLS:
                    ins.decls[target.id] = _literal(node.value, target.id, ins)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id in DECLS:
            if node.value is None:
                ins.err("STRATEGY_INVALID", f"{node.target.id} 声明缺少值")
            else:
                ins.decls[node.target.id] = _literal(node.value, node.target.id, ins)

    _check_main(ins)
    _check_decls(ins)
    return ins


def _check_main(ins: _Inspect) -> None:
    node = ins.main_node
    if node is None:
        ins.err("MAIN_MISSING", "策略必须定义 main(params, ohlcv) 函数")
        return
    if isinstance(node, ast.AsyncFunctionDef):  # pragma: no cover - 兜底
        ins.err("STRATEGY_INVALID", "main 不能是 async 函数")
        return
    args = node.args
    positional = list(args.posonlyargs) + list(args.args)
    if len(positional) < 2:
        ins.err("STRATEGY_INVALID", "main 必须接受 (params, ohlcv) 两个参数")
    if args.vararg is not None:
        ins.err("STRATEGY_INVALID", "main 不支持 *args，请显式写 (params, ohlcv)")


def _check_decls(ins: _Inspect) -> None:
    d = ins.decls
    for name in REQUIRED_DECLS:
        if name not in d:
            if name == "STRATEGY_MODE":
                ins.err("STRATEGY_INVALID", "缺少 STRATEGY_MODE 声明（当前只支持 \"signal\"）")
            else:
                ins.err("STRATEGY_INVALID", f"缺少 {name} 声明")

    mode = d.get("STRATEGY_MODE")
    if mode is not _MISSING and mode is not None and mode != "signal":
        ins.err("MODE_MISMATCH", f"STRATEGY_MODE 必须是 \"signal\"，收到 {mode!r}")

    name = d.get("NAME")
    if name is not _MISSING and name is not None:
        if not isinstance(name, str) or not name.strip():
            ins.err("STRATEGY_INVALID", "NAME 必须是非空字符串")

    desc = d.get("DESC")
    if desc is not _MISSING and desc is not None and not isinstance(desc, str):
        ins.err("STRATEGY_INVALID", "DESC 必须是字符串")

    warmup = d.get("WARMUP")
    if warmup is not _MISSING and warmup is not None:
        if not isinstance(warmup, int) or isinstance(warmup, bool) or warmup < 0:
            ins.err("STRATEGY_INVALID", "WARMUP 必须是 >= 0 的整数")

    params = d.get("PARAMS")
    if params is not _MISSING and params is not None:
        if not isinstance(params, dict):
            ins.err("PARAMS_INVALID", "PARAMS 必须是 dict")
        else:
            for k, v in params.items():
                if not isinstance(k, str) or not k:
                    ins.err("PARAMS_INVALID", f"PARAMS 键必须是非空字符串: {k!r}")
                elif not _check_scalar(v):
                    ins.err("PARAMS_INVALID", f"PARAMS[{k!r}] 必须是 JSON 标量")

    meta = d.get("PARAM_META")
    if meta is not _MISSING and meta is not None:
        _check_param_meta(meta, params if isinstance(params, dict) else {}, ins)

    protection = d.get("PROTECTION")
    if protection is not _MISSING and protection is not None:
        _check_protection(protection, ins)

    bpy = d.get("BARS_PER_YEAR")
    if bpy is not _MISSING and bpy is not None:
        if not _is_num(bpy) or float(bpy) <= 0:
            ins.err("STRATEGY_INVALID", "BARS_PER_YEAR 必须是 > 0 的数字或 None")


def _check_param_meta(meta, params: dict, ins: _Inspect) -> None:
    if not isinstance(meta, dict):
        ins.err("PARAMS_INVALID", "PARAM_META 必须是 dict")
        return
    for key, spec in meta.items():
        if not isinstance(key, str) or key not in params:
            ins.err("PARAMS_INVALID", f"PARAM_META 含未声明参数: {key!r}")
            continue
        if not isinstance(spec, dict):
            ins.err("PARAMS_INVALID", f"PARAM_META[{key!r}] 必须是 dict")
            continue
        unknown = [k for k in spec if k not in _PARAM_META_KEYS]
        if unknown:
            ins.err("PARAMS_INVALID", f"PARAM_META[{key!r}] 含未知键: {unknown}")
        ptype = spec.get("type")
        if ptype is not None and ptype not in _PARAM_TYPES:
            ins.err("PARAMS_INVALID", f"PARAM_META[{key!r}].type 必须是 {_PARAM_TYPES} 之一")
        lo, hi = spec.get("min"), spec.get("max")
        for fname, val in (("min", lo), ("max", hi), ("step", spec.get("step"))):
            if val is not None and not _is_num(val):
                ins.err("PARAMS_INVALID", f"PARAM_META[{key!r}].{fname} 必须是数字")
        if _is_num(lo) and _is_num(hi) and float(lo) > float(hi):
            ins.err("PARAMS_INVALID", f"PARAM_META[{key!r}] 的 min > max")
        if spec.get("label") is not None and not isinstance(spec.get("label"), str):
            ins.err("PARAMS_INVALID", f"PARAM_META[{key!r}].label 必须是字符串")
        if spec.get("options") is not None and not isinstance(spec.get("options"), list):
            ins.err("PARAMS_INVALID", f"PARAM_META[{key!r}].options 必须是数组")


def _check_protection(protection, ins: _Inspect) -> None:
    if not isinstance(protection, dict):
        ins.err("PROTECTION_INVALID", "PROTECTION 必须是 dict")
        return
    for key, val in protection.items():
        if key not in _PROTECTION_KEYS:
            ins.err("PROTECTION_UNKNOWN_KEY", f"未知保护键: {key!r}（只支持 {_PROTECTION_KEYS}）")
            continue
        if not _is_num(val) or not (0 < float(val) < 1):
            ins.err("PROTECTION_INVALID", f"PROTECTION[{key!r}] 必须在 (0,1) 内")


def _validate_decl_values(decls: dict) -> None:
    """执行后再验一次（防止 exec 与 AST 不一致）。"""
    ins = _Inspect(decls=dict(decls))
    _check_decls(ins)
    if ins.errors:
        e = ins.errors[0]
        raise AKError(e["code"], e["message"], detail=ins.errors)


def check_source(source: str) -> list[dict]:
    """纯 AST 校验，返回错误列表（空 = 合法）。不执行用户代码。"""
    return _inspect(source).errors


def load_strategy(source: str) -> Strategy:
    ins = _inspect(source)
    if ins.errors:
        e = ins.errors[0]
        raise AKError(e["code"], e["message"], detail=ins.errors)

    ns: dict[str, Any] = {"__name__": "ak_strategy", "__builtins__": __builtins__}
    try:
        code = compile(source, "<strategy>", "exec")
        exec(code, ns)  # noqa: S102 - 策略是用户代码，只做崩溃隔离，不做沙箱
    except Exception as exc:
        raise AKError("STRATEGY_INVALID", f"策略加载失败: {type(exc).__name__}: {exc}")

    decls = {k: ns.get(k) for k in DECLS if k in ns}
    _validate_decl_values({k: v for k, v in decls.items() if k in ins.decls})
    main_fn = ns.get("main")
    if not callable(main_fn):
        raise AKError("MAIN_MISSING", "策略必须定义 main(params, ohlcv) 函数")
    return Strategy(
        name=str(decls.get("NAME") or "").strip(),
        desc=str(decls.get("DESC") or ""),
        mode="signal",
        warmup=int(decls.get("WARMUP") or 0),
        params=dict(decls.get("PARAMS") or {}),
        param_meta=dict(decls.get("PARAM_META") or {}),
        protection=dict(decls.get("PROTECTION") or {}),
        bars_per_year=float(decls["BARS_PER_YEAR"]) if decls.get("BARS_PER_YEAR") else None,
        main=main_fn,
        source=source,
        source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
    )


def load_strategy_file(path: str) -> Strategy:
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            source = fh.read()
    except OSError as exc:
        raise AKError("STRATEGY_INVALID", f"读取策略失败: {exc}")
    return load_strategy(source)


# ============================ 参数 ============================

def _coerce(key: str, value, ptype: str | None, default):
    kind = ptype
    if kind is None and default is not None:
        kind = type(default).__name__
        if kind not in _PARAM_TYPES:
            kind = None

    if kind == "int":
        if isinstance(value, bool):
            raise AKError("PARAMS_INVALID", f"参数 {key!r} 需要整数，收到布尔值")
        try:
            f = float(value)
        except (TypeError, ValueError):
            raise AKError("PARAMS_INVALID", f"参数 {key!r} 需要整数，收到 {value!r}")
        if not math.isfinite(f) or f != int(f):
            raise AKError("PARAMS_INVALID", f"参数 {key!r} 需要整数，收到 {value!r}")
        return int(f)
    if kind == "float":
        if isinstance(value, bool):
            raise AKError("PARAMS_INVALID", f"参数 {key!r} 需要数字，收到布尔值")
        try:
            f = float(value)
        except (TypeError, ValueError):
            raise AKError("PARAMS_INVALID", f"参数 {key!r} 需要数字，收到 {value!r}")
        if not math.isfinite(f):
            raise AKError("PARAMS_INVALID", f"参数 {key!r} 需要有限数")
        return f
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0"):
            return value.strip().lower() in ("true", "1")
        raise AKError("PARAMS_INVALID", f"参数 {key!r} 需要布尔值，收到 {value!r}")
    if kind == "str":
        return value if isinstance(value, str) else str(value)
    if not _check_scalar(value):
        raise AKError("PARAMS_INVALID", f"参数 {key!r} 必须是 JSON 标量")
    return value


def resolve_params(strategy: Strategy, overrides: dict) -> dict:
    """声明默认值 + 运行覆盖；按 PARAM_META 校验类型/范围。"""
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        raise AKError("PARAMS_INVALID", "params 必须是 dict")
    unknown = [k for k in overrides if k not in strategy.params]
    if unknown:
        raise AKError("PARAM_UNKNOWN",
                      f"未知参数: {sorted(unknown)}；可用: {sorted(strategy.params)}")
    out = dict(strategy.params)
    for key, raw in overrides.items():
        meta = strategy.param_meta.get(key) or {}
        val = _coerce(key, raw, meta.get("type"), strategy.params.get(key))
        lo, hi = meta.get("min"), meta.get("max")
        if _is_num(lo) and float(val) < float(lo):
            raise AKError("PARAMS_INVALID", f"参数 {key!r}={val} 小于下限 {lo}")
        if _is_num(hi) and float(val) > float(hi):
            raise AKError("PARAMS_INVALID", f"参数 {key!r}={val} 超过上限 {hi}")
        out[key] = val
    return out


def describe_source(source: str) -> dict:
    """只读 AST 的描述信息（不执行用户代码）。"""
    ins = _inspect(source)
    d = ins.decls
    return {
        "name": d.get("NAME"),
        "desc": d.get("DESC"),
        "warmup": d.get("WARMUP"),
        "params": d.get("PARAMS") if isinstance(d.get("PARAMS"), dict) else {},
        "param_meta": d.get("PARAM_META") if isinstance(d.get("PARAM_META"), dict) else {},
        "protection": d.get("PROTECTION") if isinstance(d.get("PROTECTION"), dict) else {},
        "bars_per_year": d.get("BARS_PER_YEAR"),
        "errors": ins.errors,
    }
