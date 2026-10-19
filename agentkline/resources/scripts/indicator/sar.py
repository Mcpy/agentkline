"""
内置指标：SAR 抛物转向（v0.4.3 新增，主图叠加点线）
"""

# 只出计算值：类型/颜色/线宽/填充带/圆点等视觉由前端中间层 visual_spec.js 统一决定（脚本纯值化）。
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
    closes = [b["close"] for b in ohlcv]
    sar = [None] * n          # 首根无 SAR（原生同式：values[0] 保持 NaN）
    # 与 Vela 原生 parabolic-sar 逐行同式（vela.global.js:47266-47296）：
    #   夹逼只用「已收盘的前两根」——旧实现把当前根 low/high 也夹进去，
    #   导致反转判定（lows[i] < cur / highs[i] > cur）恒不成立 ⇒ SAR 永不转向（全绿点）。
    up = closes[1] >= closes[0]
    cur = lows[0] if up else highs[0]
    ep = highs[0] if up else lows[0]
    af = step
    for i in range(1, n):
        cur = cur + af * (ep - cur)
        if up:
            cur = min(cur, lows[i - 1], lows[i - 2] if i >= 2 else lows[i - 1])
        else:
            cur = max(cur, highs[i - 1], highs[i - 2] if i >= 2 else highs[i - 1])
        reversed_ = (lows[i] < cur) if up else (highs[i] > cur)
        if reversed_:
            up = not up
            cur = ep
            ep = highs[i] if up else lows[i]
            af = step
        elif up and highs[i] > ep:
            ep = highs[i]
            af = min(af_max, af + step)
        elif (not up) and lows[i] < ep:
            ep = lows[i]
            af = min(af_max, af + step)
        sar[i] = round(cur, 2)
    return {"lines": [{"name": "SAR", "values": sar}]}
