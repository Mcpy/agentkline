"""肯特纳通道 — Keltner Channels（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "keltner-channels"
NAME = "KC"
DESC = "肯特纳通道 — Keltner Channels（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 20, "atrLength": 10, "mult": 2, "source": "Close"}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
