"""振动升降指标 — Accumulative Swing Index（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "accumulative-swing-index"
NAME = "Accumulative Swing Index"
DESC = "振动升降指标 — Accumulative Swing Index（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"limitMove": 10, "swingLength": 10}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
