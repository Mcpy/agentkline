"""威廉鳄鱼线 — Williams Alligator（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "williams-alligator"
NAME = "Alligator"
DESC = "威廉鳄鱼线 — Williams Alligator（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"jawLength": 13, "teethLength": 8, "lipsLength": 5, "jawOffset": 8, "teethOffset": 5, "lipsOffset": 3}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
