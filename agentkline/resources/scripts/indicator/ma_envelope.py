"""均线包络 — Moving Average Envelope（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "ma-envelope"
NAME = "MA Env"
DESC = "均线包络 — Moving Average Envelope（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"maType": "SMA", "length": 20, "source": "Close", "percent": 2.5}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
