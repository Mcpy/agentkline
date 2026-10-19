"""三重指数平滑 — TRIX（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "trix"
NAME = "TRIX"
DESC = "三重指数平滑 — TRIX（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 18, "signalLength": 9}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
