"""顾比复合移动平均线 — Guppy Multiple Moving Average（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "guppy-multiple-moving-average"
NAME = "GMMA"
DESC = "顾比复合移动平均线 — Guppy Multiple Moving Average（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"source": "Close", "trader1": 3, "trader2": 5, "trader3": 8, "trader4": 10, "trader5": 12, "trader6": 15, "investor1": 30, "investor2": 35, "investor3": 40, "investor4": 45, "investor5": 50, "investor6": 60}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
