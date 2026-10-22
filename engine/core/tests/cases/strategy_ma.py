"""对齐/回归用例策略：双均线多头。"""

STRATEGY_MODE = "signal"
NAME = "case_ma"
DESC = "fast/slow 金叉做多、死叉做空（可用 direction 裁剪）"
WARMUP = 20

PARAMS = {"fast": 5, "slow": 15}
PARAM_META = {
    "fast": {"type": "int", "min": 2, "max": 60, "step": 1, "label": "快线"},
    "slow": {"type": "int", "min": 5, "max": 120, "step": 1, "label": "慢线"},
}


def main(params, ohlcv):
    fast = int(params["fast"])
    slow = int(params["slow"])
    closes = [b["close"] for b in ohlcv]
    targets, reasons = [], []
    for i in range(len(closes)):
        if i + 1 < slow:
            targets.append(0.0)
            reasons.append("warmup")
            continue
        f = sum(closes[i - fast + 1:i + 1]) / fast
        s = sum(closes[i - slow + 1:i + 1]) / slow
        targets.append(1.0 if f > s else -1.0)
        reasons.append("golden" if f > s else "dead")
    return {"target": targets, "reason": reasons}
