"""简单移动平均 — Simple Moving Average（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "sma"
NAME = "SMA"
DESC = "简单移动平均 — Simple Moving Average（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 20, "source": "Close", "offset": 0}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
