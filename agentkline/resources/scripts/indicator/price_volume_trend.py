"""价量趋势 — Price Volume Trend（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "price-volume-trend"
NAME = "PVT"
DESC = "价量趋势 — Price Volume Trend（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"showSignal": False, "signalType": "SMA", "signalLength": 21}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
