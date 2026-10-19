"""随机 RSI — Stochastic RSI（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "stochastic-rsi"
NAME = "Stoch RSI"
DESC = "随机 RSI — Stochastic RSI（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"source": "Close", "rsiLength": 14, "stochLength": 14, "kSmoothing": 3, "dLength": 3, "overbought": 80, "oversold": 20}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
