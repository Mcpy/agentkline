"""震荡指数 — Choppiness Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "choppiness-index"
NAME = "CHOP"
DESC = "震荡指数 — Choppiness Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 14, "upperBand": 61.8, "lowerBand": 38.2}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
