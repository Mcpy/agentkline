"""平均真实波幅 ATR — Average True Range（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "average-true-range"
NAME = "ATR"
DESC = "平均真实波幅 ATR — Average True Range（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 14, "smoothing": "RMA"}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
