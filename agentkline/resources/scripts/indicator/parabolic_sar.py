"""抛物线转向 SAR — Parabolic SAR（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "parabolic-sar"
NAME = "SAR"
DESC = "抛物线转向 SAR — Parabolic SAR（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"start": 0.02, "increment": 0.02, "maximum": 0.2}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
