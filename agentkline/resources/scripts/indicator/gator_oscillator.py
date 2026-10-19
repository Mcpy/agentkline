"""鳄鱼振荡器 — Gator Oscillator（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "gator-oscillator"
NAME = "Gator Oscillator"
DESC = "鳄鱼振荡器 — Gator Oscillator（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"source": "HL2", "maType": "SMMA (Wilder)", "jawLength": 13, "jawOffset": 8, "teethLength": 8, "teethOffset": 5, "lipsLength": 5, "lipsOffset": 3}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
