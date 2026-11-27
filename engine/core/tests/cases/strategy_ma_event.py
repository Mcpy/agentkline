"""对齐/回归用例事件策略：双均线多头（与 strategy_ma.py 同逻辑）。"""

STRATEGY_MODE = "event"
NAME = "case_ma_event"
DESC = "fast/slow 金叉做多、死叉做空（可用 direction 裁剪）"
WARMUP = 20

PARAMS = {"fast": 5, "slow": 15}
PARAM_META = {
    "fast": {"type": "int", "min": 2, "max": 60, "step": 1, "label": "快线"},
    "slow": {"type": "int", "min": 5, "max": 120, "step": 1, "label": "慢线"},
}


def init(params, ctx):
    return {}


def on_bar(state, bar, ctx):
    fast = int(ctx.params["fast"])
    slow = int(ctx.params["slow"])
    if ctx.t + 1 < slow:
        return {"target": 0.0, "reason": "warmup"}
    closes = [b["close"] for b in ctx.history(slow, ["close"])]
    f = sum(closes[-fast:]) / fast
    s = sum(closes[-slow:]) / slow
    return {"target": 1.0 if f > s else -1.0,
            "reason": "golden" if f > s else "dead"}
