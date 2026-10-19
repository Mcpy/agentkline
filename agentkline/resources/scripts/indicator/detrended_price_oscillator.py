"""去趋势价格振荡器 — Detrended Price Oscillator（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "detrended-price-oscillator"
NAME = "DPO"
DESC = "去趋势价格振荡器 — Detrended Price Oscillator（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 21, "source": "Close", "centered": False}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
