"""标准误差带 — Standard Error Bands（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "standard-error-bands"
NAME = "SEB"
DESC = "标准误差带 — Standard Error Bands（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 21, "mult": 2, "smoothing": 3, "smoothingType": "SMA", "source": "Close"}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
