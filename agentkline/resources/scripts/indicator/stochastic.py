"""随机指标 — Stochastic（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "stochastic"
NAME = "Stoch"
DESC = "随机指标 — Stochastic（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"kLength": 14, "kSmoothing": 3, "dLength": 3, "overbought": 80, "oversold": 20}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
