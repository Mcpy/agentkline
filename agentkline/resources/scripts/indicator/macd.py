# MACD 指标脚本（DIF/DEA 线 + 红绿柱）
# 返回 lines: DIF(黄) / DEA(蓝) / MACD柱(自动红绿)

NAME = "MACD"
DESC = "指数平滑异同移动平均：DIF/DEA 线 + 红绿柱"
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
            {"name": "DIF", "type": "line", "values": dif,
             "style": {"color": "#f5c542", "lineWidth": 1}},
            {"name": "DEA", "type": "line", "values": dea,
             "style": {"color": "#4fc3f7", "lineWidth": 1}},
            {"name": "MACD", "type": "histogram", "values": hist},
        ]
    }
