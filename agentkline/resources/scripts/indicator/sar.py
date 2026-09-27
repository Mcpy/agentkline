"""
内置指标：SAR 抛物转向（v0.4.3 新增，主图叠加点线）
"""

NAME = "SAR"
DESC = "抛物转向指标（趋势反转点跟踪）"
PARAMS = {"af_step": 0.02, "af_max": 0.2}


def main(params: dict, ohlcv: list) -> dict:
    step = float(params.get("af_step", 0.02))
    af_max = float(params.get("af_max", 0.2))
    n = len(ohlcv)
    if n < 2:
        return {"lines": []}
    highs = [b["high"] for b in ohlcv]
    lows = [b["low"] for b in ohlcv]
    sar = [None] * n
    up = True
    af = step
    ep = highs[0]
    sar[0] = lows[0]
    for i in range(1, n):
        prev = sar[i - 1]
        cur = prev + af * (ep - prev)
        if up:
            cur = min(cur, lows[i - 1], lows[i] if i else lows[i])
            if lows[i] < cur:
                up = False
                cur = ep
                ep = lows[i]
                af = step
            else:
                if highs[i] > ep:
                    ep = highs[i]
                    af = min(af + step, af_max)
        else:
            cur = max(cur, highs[i - 1], highs[i])
            if highs[i] > cur:
                up = True
                cur = ep
                ep = highs[i]
                af = step
            else:
                if lows[i] < ep:
                    ep = lows[i]
                    af = min(af + step, af_max)
        sar[i] = round(cur, 2)
    return {"lines": [{"name": "SAR", "type": "line", "values": sar,
                       "style": {"color": "#80deea", "lineWidth": 1}}]}
