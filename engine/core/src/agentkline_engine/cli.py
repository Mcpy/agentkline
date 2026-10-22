"""`ak-engine` CLI：list / run / validate-strategy。

stdout 只走哨兵 + 结果 JSON；策略与引擎的 print 全部重定向到 stderr。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

from .bars import load_bars
from .contract import ENGINE_API, RunRequest
from .errors import AKError, EXIT_ENGINE, EXIT_OK, exit_code_for
from .loader import check_source, describe_source, load_strategy
from .registry import get_engine, list_engines

SENTINEL = "__AK_RESULT__"


def _emit(payload: dict) -> None:
    sys.stdout.write(SENTINEL + "\n")
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                                allow_nan=False) + "\n")
    sys.stdout.flush()


def _read_spec(args) -> tuple[dict, Path | None]:
    base_dir = None
    if args.stdin:
        raw = sys.stdin.read()
        source = "stdin"
    elif args.spec:
        base_dir = Path(args.spec).resolve().parent
        try:
            with open(args.spec, "r", encoding="utf-8-sig") as fh:
                raw = fh.read()
        except OSError as exc:
            raise AKError("INPUT_INVALID", f"读取 spec 失败: {exc}")
        source = args.spec
    else:
        raise AKError("INPUT_INVALID", "需要 --spec 或 --stdin")
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AKError("INPUT_INVALID", f"{source} JSON 解析失败: {exc}")
    if not isinstance(spec, dict):
        raise AKError("INPUT_INVALID", "spec 必须是 JSON 对象")
    return spec, base_dir


def _resolve_path(path: str, base_dir: Path | None) -> str:
    """spec 里的相对路径先按 spec 所在目录解析，找不到再按 cwd。"""
    p = Path(path)
    if p.is_absolute():
        return str(p)
    if base_dir is not None:
        cand = base_dir / p
        if cand.exists():
            return str(cand)
    return str(p)


def _spec_strategy(spec: dict, base_dir: Path | None = None) -> str:
    st = spec.get("strategy")
    if isinstance(st, str):
        return st
    if not isinstance(st, dict):
        raise AKError("INPUT_INVALID", "spec.strategy 需要 {path} 或 {source}")
    if st.get("source"):
        return str(st["source"])
    path = st.get("path")
    if not path:
        raise AKError("INPUT_INVALID", "spec.strategy 需要 path 或 source")
    path = _resolve_path(path, base_dir)
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return fh.read()
    except OSError as exc:
        raise AKError("STRATEGY_INVALID", f"读取策略失败: {exc}")


def build_request(spec: dict, engine_override: str | None = None,
                  timeout: float | None = None, base_dir: Path | None = None) -> RunRequest:
    api = spec.get("api", ENGINE_API)
    if int(api) != ENGINE_API:
        raise AKError("API_MISMATCH", f"spec.api={api}，本框架支持 {ENGINE_API}")
    run = spec.get("run") if isinstance(spec.get("run"), dict) else {}
    bars_src = spec.get("bars")
    if isinstance(bars_src, dict) and bars_src.get("path"):
        bars_src = dict(bars_src)
        bars_src["path"] = _resolve_path(bars_src["path"], base_dir)
    req = RunRequest(
        engine=str(engine_override or spec.get("engine") or "builtin"),
        bars=load_bars(bars_src),
        strategy_source=_spec_strategy(spec, base_dir),
        params=run.get("params") or {},
        eval_start=run.get("eval_start"),
        eval_end=run.get("eval_end"),
        initial_cash=run.get("initial_cash", 10_000.0),
        fee_bps=run.get("fee_bps", 5.0),
        slippage_bps=run.get("slippage_bps", 5.0),
        direction=run.get("direction", "long_only"),
        protection=run.get("protection"),
        timeframe=str(spec.get("timeframe") or run.get("timeframe") or ""),
        symbol=str(spec.get("symbol") or ""),
        rebalance_tolerance=run.get("rebalance_tolerance", 0.0001),
        deadline=(time.monotonic() + timeout) if timeout else None,
    )
    req.validate()
    return req


def cmd_run(args) -> int:
    spec, base_dir = _read_spec(args)
    req = build_request(spec, args.engine, args.timeout, base_dir)
    eng = get_engine(req.engine)
    real_stdout = sys.stdout
    sys.stdout = sys.stderr  # 策略/引擎的 print 不得污染协议
    try:
        result = eng.run(req)
    finally:
        sys.stdout = real_stdout
    payload = result.to_dict()
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        except OSError as exc:
            raise AKError("INPUT_INVALID", f"写入结果失败: {exc}")
    _emit(payload)
    return EXIT_OK


def cmd_list(args) -> int:
    engines = list_engines()
    if args.json:
        _emit({"engines": engines})
    else:
        for e in engines:
            caps = ",".join(k for k, v in (e.get("caps") or {}).items() if v)
            print(f"{e['id']}\t{e.get('version') or '-'}\tapi={e['api']}\t{caps}")
        if not engines:
            print("(没有已注册引擎；group=agentkline.engines)")
    return EXIT_OK


def cmd_validate(args) -> int:
    try:
        with open(args.path, "r", encoding="utf-8-sig") as fh:
            source = fh.read()
    except OSError as exc:
        raise AKError("STRATEGY_INVALID", f"读取策略失败: {exc}")
    errors = check_source(source)
    info = describe_source(source)
    payload = {"ok": not errors, "name": info.get("name"), "warmup": info.get("warmup"),
               "params": info.get("params"), "errors": errors, "path": args.path}
    if args.json:
        _emit(payload)
    else:
        if errors:
            for e in errors:
                print(f"{e['code']}: {e['message']}")
        else:
            print(f"OK {info.get('name')} warmup={info.get('warmup')} params={info.get('params')}")
    return EXIT_OK if not errors else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ak-engine", description="AgentKline 引擎 CLI")
    p.add_argument("--version", action="version", version="ak-engine (engine_api=1)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="列出已注册引擎")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_list)

    pr = sub.add_parser("run", help="运行一次回测")
    pr.add_argument("--spec", help="run.json 路径")
    pr.add_argument("--stdin", action="store_true", help="从 stdin 读 spec+bars")
    pr.add_argument("--engine", help="覆盖 spec.engine")
    pr.add_argument("--out", help="结果另存为 JSON")
    pr.add_argument("--timeout", type=float, default=None, help="协作式超时（秒）")
    pr.set_defaults(func=cmd_run)

    pv = sub.add_parser("validate-strategy", help="AST 校验策略（不执行）")
    pv.add_argument("path")
    pv.add_argument("--json", action="store_true")
    pv.set_defaults(func=cmd_validate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except AKError as exc:
        _emit({"error": exc.to_dict()})
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 - 崩溃兜底
        traceback.print_exc(file=sys.stderr)
        _emit({"error": {"code": "ENGINE_INTERNAL",
                         "message": f"{type(exc).__name__}: {exc}"}})
        return EXIT_ENGINE


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
