"""科波克曲线 — Coppock Curve（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "coppock-curve"
NAME = "Coppock"
DESC = "科波克曲线 — Coppock Curve（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"wmaLength": 10, "longRoc": 14, "shortRoc": 11, "source": "Close"}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
