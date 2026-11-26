"""移动平均通道 — Moving Average Channel（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "moving-average-channel"
NAME = "MAC"
DESC = "移动平均通道 — Moving Average Channel（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"upperLength": 20, "lowerLength": 20, "upperOffset": 0, "lowerOffset": 0}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
