"""双均线 signal 策略模板（可直接被 ak-engine 加载）。

用法：
    ak-engine run --spec engine/examples/run.json
"""

STRATEGY_MODE = "signal"
NAME = "双均线"
DESC = "fast/slow 金叉做多、死叉空仓；带 5% 止损 / 10% 止盈"
WARMUP = 60

PARAMS = {"fast": 10, "slow": 30}

PARAM_META = {
    "fast": {"type": "int", "min": 2, "max": 200, "step": 1, "label": "快线"},
    "slow": {"type": "int", "min": 5, "max": 400, "step": 1, "label": "慢线"},
}

PROTECTION = {"stop_loss_pct": 0.05, "take_profit_pct": 0.10}


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
