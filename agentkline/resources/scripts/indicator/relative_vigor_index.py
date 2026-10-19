"""相对活力指数 — Relative Vigor Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "relative-vigor-index"
NAME = "RVGI"
DESC = "相对活力指数 — Relative Vigor Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 10}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
