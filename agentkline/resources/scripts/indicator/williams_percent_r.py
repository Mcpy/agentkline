"""威廉 %R — Williams %R（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "williams-percent-r"
NAME = "%R"
DESC = "威廉 %R — Williams %R（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 14, "source": "Close", "overbought": -20, "oversold": -80}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
