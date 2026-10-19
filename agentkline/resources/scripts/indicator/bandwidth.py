"""布林带宽 — Bollinger Bands Width（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "bandwidth"
NAME = "BandWidth"
DESC = "布林带宽 — Bollinger Bands Width（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 20, "source": "Close", "mult": 2, "lookback": 125, "showSqueeze": True, "showBulge": True}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
