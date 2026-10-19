"""可变指数动态平均 — Variable Index Dynamic Average（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "vidya"
NAME = "VIDYA"
DESC = "可变指数动态平均 — Variable Index Dynamic Average（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"source": "Close", "length": 12, "scaler": "Momentum (|CMO|)", "scalerLength": 9, "refLength": 30, "flatThreshold": 0.05, "atrLength": 14}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
