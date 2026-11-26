"""多数规则 — Majority Rule（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "majority-rule"
NAME = "Majority Rule"
DESC = "多数规则 — Majority Rule（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 14}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
