"""平滑移动平均 — Smoothed Moving Average（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "rma"
NAME = "RMA"
DESC = "平滑移动平均 — Smoothed Moving Average（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"source": "Close", "length": 14}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
