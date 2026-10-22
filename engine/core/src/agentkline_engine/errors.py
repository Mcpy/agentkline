"""引擎错误码与退出码。

错误码是跨进程契约：后端只认 code，不解析 message。
"""
from __future__ import annotations

# 退出码（CLI 进程）
EXIT_OK = 0
EXIT_INPUT = 2      # 输入/契约错误
EXIT_CRASH = 3      # 崩溃（进程死掉，由后端判定）
EXIT_TIMEOUT = 4    # 超时
EXIT_ENGINE = 5     # 引擎内部错误

# 错误码 → 退出码
_EXIT_BY_CODE = {
    "INPUT_INVALID": EXIT_INPUT,
    "API_MISMATCH": EXIT_INPUT,
    "ENGINE_NOT_FOUND": EXIT_INPUT,
    "BARS_INVALID": EXIT_INPUT,
    "STRATEGY_INVALID": EXIT_INPUT,
    "STRATEGY_SOURCE_EMPTY": EXIT_INPUT,
    "MODE_MISMATCH": EXIT_INPUT,
    "MAIN_MISSING": EXIT_INPUT,
    "PROTECTION_UNKNOWN_KEY": EXIT_INPUT,
    "PROTECTION_INVALID": EXIT_INPUT,
    "PARAMS_INVALID": EXIT_INPUT,
    "PARAM_UNKNOWN": EXIT_INPUT,
    "TARGET_INVALID": EXIT_INPUT,
    "TARGET_LENGTH": EXIT_INPUT,
    "TARGET_NONFINITE": EXIT_INPUT,
    "RUN_TIMEOUT": EXIT_TIMEOUT,
    "ENGINE_INTERNAL": EXIT_ENGINE,
}

CODES = tuple(_EXIT_BY_CODE)


class AKError(Exception):
    """带错误码的引擎错误。"""

    def __init__(self, code: str, message: str, detail=None):
        if code not in _EXIT_BY_CODE:
            code = "ENGINE_INTERNAL"
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail

    @property
    def exit_code(self) -> int:
        return _EXIT_BY_CODE[self.code]

    def to_dict(self) -> dict:
        out = {"code": self.code, "message": self.message}
        if self.detail is not None:
            out["detail"] = self.detail
        return out


class RunTimeout(AKError):
    def __init__(self, message: str = "运行超时"):
        super().__init__("RUN_TIMEOUT", message)


def exit_code_for(exc: BaseException) -> int:
    if isinstance(exc, AKError):
        return exc.exit_code
    return EXIT_ENGINE
