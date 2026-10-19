"""之字转向 — ZigZag（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "zigzag"
NAME = "ZigZag"
DESC = "之字转向 — ZigZag（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"deviation": 5, "depth": 10}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
