# RSI 指标

NAME = "RSI"
DESC = "相对强弱指标（Wilder 平滑）"
SUBPLOT = True  # v0.4.3：副图族声明（add_indicator 未显式传 subplot 时自动建/删副图）
PARAMS = {"period": 14}


def main(params, ohlcv):
    n = int(params.get("period", 14))
    close = [b["close"] for b in ohlcv]
    rsi = [None] * len(close)
    g = l = 0.0
    for i in range(1, len(close)):
        ch = close[i] - close[i - 1]
        up, dn = max(ch, 0), max(-ch, 0)
        if i <= n:
            g += up
            l += dn
            if i == n:
                g /= n
                l /= n
                rsi[i] = 100 - 100 / (1 + (g / l if l else 1e9))
        else:
            g = (g * (n - 1) + up) / n
            l = (l * (n - 1) + dn) / n
            rsi[i] = 100 - 100 / (1 + (g / l if l else 1e9))
    return {"lines": [{"name": "RSI", "type": "line", "values": rsi,
                       "style": {"color": "#b39ddb", "lineWidth": 1}}]}
