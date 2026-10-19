"""负量指数 — Negative Volume Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "negative-volume-index"
NAME = "Negative Volume Index"
DESC = "负量指数 — Negative Volume Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"base": 1000, "showSignal": True, "signalLength": 255, "colorMode": "Position vs Average"}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
