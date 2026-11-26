"""趋势强度指数 — Trend Strength Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "trend-strength-index"
NAME = "Trend Strength Index"
DESC = "趋势强度指数 — Trend Strength Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 14, "source": "Close"}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
