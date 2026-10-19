"""移动平均（多类型） — Moving Average（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "moving-average"
NAME = "MA"
DESC = "移动平均（多类型） — Moving Average（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"maType": "SMA", "length": 20, "source": "Close", "showMa2": False, "ma2Type": "SMA", "ma2Length": 50, "ma2Source": "Close", "almaOffset": 0.85, "almaSigma": 6, "lsmaOffset": 0, "offset": 0}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
