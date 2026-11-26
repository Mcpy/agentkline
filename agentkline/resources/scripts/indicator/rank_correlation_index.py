"""等级相关指数 — Rank Correlation Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "rank-correlation-index"
NAME = "RCI"
DESC = "等级相关指数 — Rank Correlation Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 12, "source": "Close", "overbought": 0.8, "oversold": -0.8}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
