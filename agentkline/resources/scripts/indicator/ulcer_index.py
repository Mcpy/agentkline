"""溃疡指数 — Ulcer Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "ulcer-index"
NAME = "Ulcer Index"
DESC = "溃疡指数 — Ulcer Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 14, "source": "Close", "threshold": 5}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
