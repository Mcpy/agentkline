"""指数异同移动平均 — MACD（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "macd"
NAME = "MACD"
DESC = "指数异同移动平均 — MACD（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"fastLength": 12, "slowLength": 26, "signalLength": 9, "source": "Close"}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
