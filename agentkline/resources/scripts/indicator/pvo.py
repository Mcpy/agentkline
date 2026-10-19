"""百分比成交量振荡器 — Percentage Volume Oscillator（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "pvo"
NAME = "PVO"
DESC = "百分比成交量振荡器 — Percentage Volume Oscillator（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"fastLength": 12, "slowLength": 26, "signalLength": 9}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
