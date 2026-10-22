"""引擎子进程：spec → stdin，结果 ← stdout 哨兵；超时按进程组 kill。

约定（与 engine/core 的 CLI 一致）：
- stdout 第一行哨兵 `__AK_RESULT__`，随后一行结果 JSON；引擎/策略的 print 全在 stderr；
- 不落盘：bars/策略源码/结果全程内存；
- 超时用 `os.killpg`（引擎可能 fork，单杀父进程会留孤儿）；
- 错误统一成 EngineRunError，code 与 CLI 同一套。
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

SENTINEL = "__AK_RESULT__"
STDERR_TAIL = 4000


class EngineRunError(Exception):
    def __init__(self, code: str, message: str, detail=None,
                 stderr_tail: str = "", exit_code: int | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail
        self.stderr_tail = stderr_tail
        self.exit_code = exit_code

    def to_dict(self) -> dict:
        out = {"code": self.code, "message": self.message}
        if self.detail is not None:
            out["detail"] = self.detail
        if self.stderr_tail:
            out["stderr"] = self.stderr_tail
        if self.exit_code is not None:
            out["exit_code"] = self.exit_code
        return out


def engine_cmd() -> list[str]:
    """优先当前解释器同目录的 ak-engine（venv 内），其次 PATH，最后 python -m。"""
    exe = Path(sys.executable).with_name("ak-engine")
    if exe.exists():
        return [str(exe)]
    found = shutil.which("ak-engine")
    if found:
        return [found]
    return [sys.executable, "-m", "agentkline_engine.cli"]


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.communicate(timeout=5)
    except Exception:
        pass


def _parse_result(raw: str) -> dict | None:
    lines = (raw or "").splitlines()
    for i, line in enumerate(lines):
        if line.strip() == SENTINEL:
            body = "\n".join(lines[i + 1:]).strip()
            if not body:
                return None
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return None
    return None


def invoke(args: list[str], payload: str | None = None, timeout: float = 120.0) -> dict:
    cmd = engine_cmd() + args
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        out, err = proc.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        raise EngineRunError("RUN_TIMEOUT", f"引擎运行超过 {timeout:g}s，进程组已终止")
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    tail = (err or "")[-STDERR_TAIL:]
    data = _parse_result(out or "")
    if data is None:
        raise EngineRunError(
            "ENGINE_CRASH",
            f"引擎没有输出结果（exit={proc.returncode}）",
            stderr_tail=tail, exit_code=proc.returncode,
        )
    err_obj = data.get("error")
    if isinstance(err_obj, dict):
        raise EngineRunError(
            str(err_obj.get("code") or "ENGINE_INTERNAL"),
            str(err_obj.get("message") or "引擎报错"),
            detail=err_obj.get("detail"), stderr_tail=tail,
            exit_code=proc.returncode,
        )
    data["_elapsed_ms"] = elapsed_ms
    return data


def list_engines(timeout: float = 30.0) -> list[dict]:
    data = invoke(["list", "--json"], timeout=timeout)
    engines = data.get("engines")
    if not isinstance(engines, list):
        raise EngineRunError("ENGINE_INTERNAL", "ak-engine list 返回格式不对")
    return engines


def run_spec(spec: dict, timeout: float = 120.0) -> dict:
    return invoke(["run", "--stdin"], json.dumps(spec, ensure_ascii=False), timeout=timeout)
