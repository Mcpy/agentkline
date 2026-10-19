"""钱德-克罗尔止损 — Chande Kroll Stop（Vela 内置研究移植，值由 Python 单源计算）

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = "chande-kroll-stop"
NAME = "CKS"
DESC = "钱德-克罗尔止损 — Chande Kroll Stop（Vela 内置研究移植，值由 Python 单源计算）"
PARAMS = {"p": 10, "x": 1, "q": 9}
SUBPLOT = False


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
