"""终极振荡器 — Ultimate Oscillator（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "ultimate-oscillator"
NAME = "UO"
DESC = "终极振荡器 — Ultimate Oscillator（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"fastLength": 7, "middleLength": 14, "slowLength": 28, "overbought": 70, "oversold": 30}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
