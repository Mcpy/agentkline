"""中间价 — Median Price（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "median-price"
NAME = "Median Price"
DESC = "中间价 — Median Price（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
