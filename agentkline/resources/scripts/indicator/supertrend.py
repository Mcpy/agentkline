"""超级趋势 — SuperTrend（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "supertrend"
NAME = "SuperTrend"
DESC = "超级趋势 — SuperTrend（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"atrLength": 10, "mult": 3}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
