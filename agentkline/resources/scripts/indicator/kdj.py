# KDJ 随机指标

NAME = "KDJ"
DESC = "随机指标 K/D/J 三线"
SUBPLOT = True  # v0.4.3：副图族声明（add_indicator 未显式传 subplot 时自动建/删副图）
PARAMS = {"n": 9}


def main(params, ohlcv):
    n = int(params.get("n", 9))
    high = [b["high"] for b in ohlcv]
    low = [b["low"] for b in ohlcv]
    close = [b["close"] for b in ohlcv]
    K = [None] * len(close)
    D = [None] * len(close)
    J = [None] * len(close)
    pk = pd = 50.0
    for i in range(len(close)):
        s = max(0, i - n + 1)
        hh = max(high[s:i + 1])
        ll = min(low[s:i + 1])
        rsv = 50 if hh == ll else (close[i] - ll) / (hh - ll) * 100
        pk = (2 / 3) * pk + (1 / 3) * rsv
        pd = (2 / 3) * pd + (1 / 3) * pk
        K[i] = pk
        D[i] = pd
        J[i] = 3 * pk - 2 * pd
    return {"lines": [
        {"name": "K", "type": "line", "values": K, "style": {"color": "#f5c542", "lineWidth": 1}},
        {"name": "D", "type": "line", "values": D, "style": {"color": "#4fc3f7", "lineWidth": 1}},
        {"name": "J", "type": "line", "values": J, "style": {"color": "#b39ddb", "lineWidth": 1}},
    ]}
