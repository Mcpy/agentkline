"""平均趋向指数 ADX — Average Directional Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "average-directional-index"
NAME = "ADX"
DESC = "平均趋向指数 ADX — Average Directional Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"diLength": 14, "adxLength": 14, "keyLevel": 25}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
