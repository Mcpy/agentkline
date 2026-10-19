"""真实强度指数 — True Strength Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "true-strength-index"
NAME = "TSI"
DESC = "真实强度指数 — True Strength Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"longLength": 25, "shortLength": 13, "signalLength": 13}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
