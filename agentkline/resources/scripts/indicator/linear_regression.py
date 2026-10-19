"""线性回归曲线 — Linear Regression Curve（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "linear-regression"
NAME = "LinReg"
DESC = "线性回归曲线 — Linear Regression Curve（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"mode": "Curve", "length": 100, "source": "Close"}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
