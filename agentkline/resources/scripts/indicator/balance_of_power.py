"""力量平衡 — Balance of Power（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "balance-of-power"
NAME = "BOP"
DESC = "力量平衡 — Balance of Power（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"smoothing": False, "smoothLength": 14}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
