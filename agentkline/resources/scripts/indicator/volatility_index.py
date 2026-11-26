"""波动率指数 — Volatility Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "volatility-index"
NAME = "Vol Index"
DESC = "波动率指数 — Volatility Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 10, "mult": 3, "smoothing": "RMA"}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
