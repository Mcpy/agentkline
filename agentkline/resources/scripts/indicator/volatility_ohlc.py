"""O-H-L-C 波动率 — Volatility O-H-L-C（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "volatility-ohlc"
NAME = "Vol OHLC"
DESC = "O-H-L-C 波动率 — Volatility O-H-L-C（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 10, "marketClosed": 0, "daysPerYear": 252}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
