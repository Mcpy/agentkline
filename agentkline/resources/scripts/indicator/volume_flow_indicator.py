"""成交量流量指标 — Volume Flow Indicator（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "volume-flow-indicator"
NAME = "Volume Flow Indicator"
DESC = "成交量流量指标 — Volume Flow Indicator（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 130, "coef": 0.2, "volCoef": 2.5, "volLength": 30, "smooth": True, "smoothLength": 3, "showSignal": True, "signalLength": 5}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
