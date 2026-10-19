"""力度指数 — Force Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "force-index"
NAME = "FI"
DESC = "力度指数 — Force Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 13}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
