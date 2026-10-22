"""第三方引擎最小骨架（复制到自己的包里改）。

注册（你的 pyproject.toml）：

    [project.entry-points."agentkline.engines"]
    myengine = "my_pkg.engine:MyEngine"

之后 `ak-engine list --json` 就能看到 myengine，后端只需传 engine 名。
"""
from agentkline_engine.contract import ENGINE_API, RunRequest, RunResult


class MyEngine:
    id = "myengine"
    version = "0.1.0"
    api = ENGINE_API                 # 必须等于框架支持的 engine_api

    # 能力声明：false 的项后端会禁用对应界面能力
    caps = {
        "signal": False,             # 接受 target 数组
        "event": True,               # 事件式（initialize/handle_data）
        "short": False,
        "leverage": False,
        "multi_symbol": False,
        "protection": False,
    }

    # 结果里的执行假设（固定键见 core.contract.DEFAULT_ASSUMPTIONS）
    assumptions = {
        "fill_rule": "next_open",
        "bar_close_policy": "closed_bars_only",
        "lot_policy": "continuous",
        "leverage": 1,
        "funding_mode": "not_modeled",
    }

    def run(self, req: RunRequest) -> RunResult:
        # 1) 自己决定怎么读 req.bars / req.strategy_source
        # 2) 自己撮合或复用 agentkline_engine.matching.MatchingEngine
        # 3) 用 agentkline_engine.result.build_result 装配 schema=1 结果
        #
        # 硬性要求：
        # - 不 import fastapi/uvicorn/agentkline；你在子进程里跑，只有 stdin/stdout；
        # - 用户代码的 print 会被 CLI 重定向到 stderr，可以放心 print；
        # - 超时看 req.deadline（time.monotonic 绝对值），到点抛 RunTimeout。
        raise NotImplementedError("TODO: 实现你的撮合")
