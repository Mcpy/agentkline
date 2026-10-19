"""SMI 遍历 — SMI Ergodic Oscillator（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "smi-ergodic"
NAME = "SMIE"
DESC = "SMI 遍历 — SMI Ergodic Oscillator（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"longLength": 20, "shortLength": 5, "signalLength": 5, "display": "Indicator"}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
