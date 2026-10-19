"""蔡金资金流 — Chaikin Money Flow（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "chaikin-money-flow"
NAME = "CMF"
DESC = "蔡金资金流 — Chaikin Money Flow（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 20}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
