"""沙夫趋势周期 — Schaff Trend Cycle（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "schaff-trend-cycle"
NAME = "Schaff Trend Cycle"
DESC = "沙夫趋势周期 — Schaff Trend Cycle（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"source": "Close", "fastLength": 23, "slowLength": 50, "cycleLength": 10, "factor": 0.5, "upper": 75, "lower": 25}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
