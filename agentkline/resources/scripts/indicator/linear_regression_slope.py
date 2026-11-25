"""线性回归斜率 — Linear Regression Slope（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "linear-regression-slope"
NAME = "LRS"
DESC = "线性回归斜率 — Linear Regression Slope（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 100, "source": "Close"}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
