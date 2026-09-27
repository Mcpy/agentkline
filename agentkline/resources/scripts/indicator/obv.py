"""
内置指标：OBV 能量潮（v0.4.3 新增，副图单线）
"""

NAME = "OBV"
DESC = "能量潮：成交量按收盘涨跌累加（量价背离观察）"
SUBPLOT = True  # v0.4.3：副图族声明（add_indicator 未显式传 subplot 时自动建/删副图）
PARAMS = {}


def main(params: dict, ohlcv: list) -> dict:
    if not ohlcv:
        return {"lines": []}
    obv = [0.0]
    for i in range(1, len(ohlcv)):
        c, pc = ohlcv[i]["close"], ohlcv[i - 1]["close"]
        v = ohlcv[i].get("volume") or 0
        obv.append(obv[-1] + (v if c > pc else -v if c < pc else 0))
    return {"lines": [{"name": "OBV", "type": "line", "values": obv,
                       "style": {"color": "#90a4ae", "lineWidth": 1}}]}
