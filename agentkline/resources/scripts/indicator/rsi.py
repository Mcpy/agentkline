# RSI 指标

# 只出计算值：类型/颜色/线宽/填充带/圆点等视觉由前端中间层 visual_spec.js 统一决定（脚本纯值化）。
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
    return {"lines": [{"name": "RSI", "values": rsi}]}
