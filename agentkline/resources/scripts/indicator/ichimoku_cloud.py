"""一目均衡表 — Ichimoku Cloud（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "ichimoku-cloud"
NAME = "Ichimoku"
DESC = "一目均衡表 — Ichimoku Cloud（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"conversionLength": 9, "baseLength": 26, "spanBLength": 52, "laggingLength": 26, "displacement": 26}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
