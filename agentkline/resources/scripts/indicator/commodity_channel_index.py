"""顺势指标 CCI — Commodity Channel Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "commodity-channel-index"
NAME = "CCI"
DESC = "顺势指标 CCI — Commodity Channel Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 20, "source": "HLC3", "upper": 100, "lower": -100}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
