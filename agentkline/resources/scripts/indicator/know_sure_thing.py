"""明确趋势 KST — Know Sure Thing（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "know-sure-thing"
NAME = "KST"
DESC = "明确趋势 KST — Know Sure Thing（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"rocLength1": 10, "rocLength2": 15, "rocLength3": 20, "rocLength4": 30, "smaLength1": 10, "smaLength2": 10, "smaLength3": 10, "smaLength4": 15, "signalLength": 9}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
