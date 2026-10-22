"""内置引擎（随主包分发）。

约束：只能依赖 `agentkline_engine`，不得 import fastapi/uvicorn/state/vela，
保证 `ak-engine` 子进程不会把后端依赖拖进来。
"""
