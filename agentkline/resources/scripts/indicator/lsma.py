"""最小二乘移动平均 — Least Squares Moving Average（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "lsma"
NAME = "LSMA"
DESC = "最小二乘移动平均 — Least Squares Moving Average（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"source": "Close", "length": 25, "offset": 0}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
