"""康纳斯 RSI — Connors RSI（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "connors-rsi"
NAME = "CRSI"
DESC = "康纳斯 RSI — Connors RSI（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"rsiLength": 3, "streakLength": 2, "rankLength": 100, "overbought": 90, "oversold": 10}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
