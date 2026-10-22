"""内置策略模板：双均线（signal 内核）。

契约（v0.6.1）：
  STRATEGY_MODE/NAME/WARMUP/PARAMS 必填；PARAM_META/PROTECTION 可选；
  main(params, ohlcv) -> {"target": [...], "reason": [...]}
target 是目标权重（-1~1）：1=满仓做多，0=空仓，-1=满仓做空；
本策略只做多，方向过滤交给运行参数（long_only/short_only/both）。
"""

STRATEGY_MODE = "signal"
NAME = "双均线"
DESC = "快线上穿慢线做多、下穿空仓"
WARMUP = 30  # ≥ slow；调大 slow 时同步调大

PARAMS = {"fast": 10, "slow": 30}

PARAM_META = {
    "fast": {"type": "int", "min": 2, "max": 200, "step": 1, "label": "快线"},
    "slow": {"type": "int", "min": 5, "max": 400, "step": 1, "label": "慢线"},
}

# 保护单默认不开：运行回测时在表单里填止损/止盈即可，或在这里声明：
# PROTECTION = {"stop_loss_pct": 0.08, "take_profit_pct": 0.20}


def main(params, ohlcv):
    fast = int(params["fast"])
    slow = int(params["slow"])
    if fast >= slow:
        fast = max(2, slow - 1)

    closes = [b["close"] for b in ohlcv]
    targets, reasons = [], []
    for i in range(len(closes)):
        if i + 1 < slow:
            targets.append(0.0)
            reasons.append("warmup")
            continue
        f = sum(closes[i - fast + 1:i + 1]) / fast
        s = sum(closes[i - slow + 1:i + 1]) / slow
        if f > s:
            targets.append(1.0)
            reasons.append("golden_cross")
        else:
            targets.append(0.0)
            reasons.append("dead_cross")
    return {"target": targets, "reason": reasons}
