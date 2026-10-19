"""变动率 ROC — Rate of Change（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "rate-of-change"
NAME = "ROC"
DESC = "变动率 ROC — Rate of Change（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 9, "source": "Close", "mode": "ROC %"}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
