"""MA 与 EMA 交叉 — MA with EMA Cross（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "ma-with-ema-cross"
NAME = "MA/EMA Cross"
DESC = "MA 与 EMA 交叉 — MA with EMA Cross（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"maLength": 10, "emaLength": 10, "source": "Close"}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
