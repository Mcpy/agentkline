"""MA 交叉 — MA Cross（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "ma-cross"
NAME = "MA Cross"
DESC = "MA 交叉 — MA Cross（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"shortLength": 9, "longLength": 26, "source": "Close"}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
