"""52 周高低点 — 52 Week High/Low（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "52-week-high-low"
NAME = "52W H/L"
DESC = "52 周高低点 — 52 Week High/Low（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"weeks": 52, "showAllTime": False}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
