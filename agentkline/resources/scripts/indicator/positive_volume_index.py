"""正量指数 — Positive Volume Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "positive-volume-index"
NAME = "Positive Volume Index"
DESC = "正量指数 — Positive Volume Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"source": "Close", "base": 1000, "showSignal": True, "signalLength": 255}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
