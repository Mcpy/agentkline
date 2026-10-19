"""相对波动率指数 — Relative Volatility Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "relative-volatility-index"
NAME = "RVI"
DESC = "相对波动率指数 — Relative Volatility Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"stdevLength": 10, "smoothLength": 14, "smoothType": "EMA", "overbought": 80, "oversold": 20}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
