"""三移动平均线 — Moving Average Triple（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "moving-average-triple"
NAME = "MA Triple"
DESC = "三移动平均线 — Moving Average Triple（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"maType": "SMA", "source": "Close", "length1": 14, "length2": 21, "length3": 35}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
