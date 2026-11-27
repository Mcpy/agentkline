"""内置策略模板：双均线（event 内核，0.7.5）。

契约（0.7.5）：
  STRATEGY_MODE/NAME/WARMUP/PARAMS 必填；PARAM_META/PROTECTION 可选；
  on_bar(state, bar, ctx) -> {"target": x, "reason": "..."} 或 float target。
target 是目标权重（-1~1），t 收盘决策、t+1 开盘成交，与 signal 版同一套撮合；
本策略只做多，方向过滤交给运行参数（long_only/short_only/both）。

state 必须 JSON 可序列化；本策略不依赖跨 bar 状态，用 ctx.history 现算。
"""

STRATEGY_MODE = "event"
NAME = "双均线（事件）"
DESC = "快线上穿慢线做多、下穿空仓（逐 bar 事件版，与 signal 版逐笔一致）"
WARMUP = 30  # ≥ slow；调大 slow 时同步调大

PARAMS = {"fast": 10, "slow": 30}

PARAM_META = {
    "fast": {"type": "int", "min": 2, "max": 200, "step": 1, "label": "快线"},
    "slow": {"type": "int", "min": 5, "max": 400, "step": 1, "label": "慢线"},
}


def on_bar(state, bar, ctx):
    fast = int(ctx.params["fast"])
    slow = int(ctx.params["slow"])
    if fast >= slow:
        fast = max(2, slow - 1)
    closes = [b["close"] for b in ctx.history(slow)]
    if len(closes) < slow:
        return {"target": 0.0, "reason": "warmup"}
    f = sum(closes[-fast:]) / fast
    s = sum(closes) / slow
    return {"target": 1.0 if f > s else 0.0,
            "reason": "golden_cross" if f > s else "dead_cross"}
