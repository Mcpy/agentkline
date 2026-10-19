"""资金流量指数 MFI — Money Flow Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "money-flow-index"
NAME = "MFI"
DESC = "资金流量指数 MFI — Money Flow Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 14, "overbought": 80, "oversold": 20}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
