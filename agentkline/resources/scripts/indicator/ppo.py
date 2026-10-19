"""百分比价格振荡器 — Percentage Price Oscillator（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "ppo"
NAME = "PPO"
DESC = "百分比价格振荡器 — Percentage Price Oscillator（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"source": "Close", "fastLength": 12, "slowLength": 26, "maType": "EMA", "signalLength": 9, "signalType": "EMA"}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
