"""典型价格 — Typical Price（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "typical-price"
NAME = "Typical Price"
DESC = "典型价格 — Typical Price（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
