"""蔡金振荡器 — Chaikin Oscillator（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "chaikin-oscillator"
NAME = "Chaikin Osc"
DESC = "蔡金振荡器 — Chaikin Oscillator（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"fastLength": 3, "slowLength": 10}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
