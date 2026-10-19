"""费雪变换 — Fisher Transform（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "fisher-transform"
NAME = "Fisher"
DESC = "费雪变换 — Fisher Transform（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 9}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
