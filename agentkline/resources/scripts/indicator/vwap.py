"""成交量加权均价 — Volume Weighted Average Price（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "vwap"
NAME = "VWAP"
DESC = "成交量加权均价 — Volume Weighted Average Price（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"anchor": "Session", "source": "HLC3", "bandsMode": "Standard Deviation", "band1": True, "band1Mult": 1, "band2": False, "band2Mult": 2, "band3": False, "band3Mult": 3, "hideDwm": True}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
