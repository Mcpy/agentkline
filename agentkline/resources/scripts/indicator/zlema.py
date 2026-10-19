"""零延迟 EMA — Zero-Lag Exponential Moving Average（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "zlema"
NAME = "ZLEMA"
DESC = "零延迟 EMA — Zero-Lag Exponential Moving Average（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"source": "Close", "length": 21}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
