"""钱德动量振荡器 — Chande Momentum Oscillator（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "chande-momentum-oscillator"
NAME = "CMO"
DESC = "钱德动量振荡器 — Chande Momentum Oscillator（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"length": 9, "source": "Close", "overbought": 50, "oversold": -50}
SUBPLOT = True


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
