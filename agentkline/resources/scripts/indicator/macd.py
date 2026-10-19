# MACD 指标脚本（DIF/DEA 线 + 红绿柱）
# 返回 lines: DIF / DEA / MACD 柱（柱色由中间层按动能四态自动上色）

# 只出计算值：类型/颜色/线宽/填充带/圆点等视觉由前端中间层 visual_spec.js 统一决定（脚本纯值化）。
NAME = "MACD"
DESC = "指数平滑异同移动平均：DIF/DEA 线 + 红绿柱"
SUBPLOT = True  # v0.4.3：副图族声明（add_indicator 未显式传 subplot 时自动建/删副图）
PARAMS = {"fast": 12, "slow": 26, "signal": 9}


def _ema(vals, n):
    out = [None] * len(vals)
    k = 2.0 / (n + 1)
    prev = None
    for i, v in enumerate(vals):
        if v is None:
            out[i] = prev
            continue
        prev = v if prev is None else v * k + prev * (1 - k)
        out[i] = prev
    return out


def main(params, ohlcv):
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 26))
    sig = int(params.get("signal", 9))

    close = [b.get("close") for b in ohlcv]
    ema_f = _ema(close, fast)
    ema_s = _ema(close, slow)
    dif = [(f - s) if (f is not None and s is not None) else None
           for f, s in zip(ema_f, ema_s)]
    dea = _ema(dif, sig)
    hist = [(d - e) * 2 if (d is not None and e is not None) else None
            for d, e in zip(dif, dea)]

    return {
        "lines": [
            {"name": "DIF", "values": dif},
            {"name": "DEA", "values": dea},
            {"name": "MACD", "values": hist},
        ]
    }
