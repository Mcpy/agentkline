"""
AgentKline - 脚本执行引擎
L1 沙箱：直接 exec（内部调试用）
"""
import sys
import io
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agentkline.script")


class ScriptEngine:
    """Python 脚本执行引擎"""

    def __init__(self, scripts_dir: str):
        self.scripts_dir = Path(scripts_dir)
        self.scripts_dir.mkdir(parents=True, exist_ok=True)

    def resolve_path(self, path: str) -> Optional[Path]:
        """解析脚本路径（支持相对路径）"""
        p = Path(path)
        if p.is_absolute():
            if p.exists():
                return p
            return None
        # 相对路径：相对于 scripts 目录
        full = self.scripts_dir / path
        if full.exists():
            return full
        # 也尝试相对于项目根目录
        full2 = self.scripts_dir.parent / path
        if full2.exists():
            return full2
        return None

    def run_script(self, path: str, params: dict = None) -> dict:
        """
        执行脚本，返回 {"data": [...]} 或 {"error": "..."}
        脚本必须定义 main(params) 函数
        """
        resolved = self.resolve_path(path)
        if not resolved:
            return {"error": f"SCRIPT_NOT_FOUND: {path}"}

        try:
            code = resolved.read_text(encoding="utf-8")
        except Exception as e:
            return {"error": f"SCRIPT_READ_ERROR: {e}"}

        # 执行脚本
        try:
            result = self._exec_script(code, params or {}, str(resolved))
            return result
        except Exception as e:
            logger.error(f"Script execution error: {path}: {e}")
            return {"error": f"SCRIPT_EXEC_ERROR: {str(e)}"}

    def run_indicator_script(self, path: str, ohlcv: list[dict], params: dict = None) -> dict:
        """
        执行指标脚本
        脚本必须定义 main(params, ohlcv) 函数
        返回 {"values": [...]} 或 {"error": "..."}
        """
        resolved = self.resolve_path(path)
        if not resolved:
            return {"error": f"SCRIPT_NOT_FOUND: {path}"}

        try:
            code = resolved.read_text(encoding="utf-8")
        except Exception as e:
            return {"error": f"SCRIPT_READ_ERROR: {e}"}

        try:
            result = self._exec_indicator_script(code, params or {}, ohlcv, str(resolved))
            return result
        except Exception as e:
            logger.error(f"Indicator script error: {path}: {e}")
            return {"error": f"SCRIPT_EXEC_ERROR: {str(e)}"}

    def _exec_script(self, code: str, params: dict, filepath: str) -> dict:
        """在隔离命名空间中执行脚本"""
        # 准备执行环境
        namespace = {
            "__name__": "__main__",
            "__file__": filepath,
            "params": params,
        }

        # 捕获 stdout
        old_stdout = sys.stdout
        captured = io.StringIO()
        sys.stdout = captured

        try:
            exec(code, namespace)

            # 查找 main 函数
            main_func = namespace.get("main")
            if main_func is None:
                return {"error": "SCRIPT_NO_MAIN: 脚本必须定义 main(params) 函数"}

            # 调用 main
            result = main_func(params)

            if result is None:
                return {"error": "SCRIPT_RETURN_NONE: main() 返回了 None"}

            # 处理返回值
            if isinstance(result, list):
                return {"data": result}
            elif isinstance(result, dict):
                return {"data": result.get("data", result)}
            else:
                return {"data": result}

        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        if output:
            logger.info(f"Script output: {output[:500]}")

    def _exec_indicator_script(self, code: str, params: dict, ohlcv: list, filepath: str) -> dict:
        """执行指标脚本"""
        namespace = {
            "__name__": "__main__",
            "__file__": filepath,
            "params": params,
            "ohlcv": ohlcv,
        }

        old_stdout = sys.stdout
        captured = io.StringIO()
        sys.stdout = captured

        try:
            exec(code, namespace)

            main_func = namespace.get("main")
            if main_func is None:
                return {"error": "SCRIPT_NO_MAIN: 指标脚本必须定义 main(params, ohlcv) 函数"}

            # 尝试两种签名
            import inspect
            sig = inspect.signature(main_func)
            if len(sig.parameters) >= 2:
                result = main_func(params, ohlcv)
            else:
                result = main_func(params)

            if result is None:
                return {"error": "SCRIPT_RETURN_NONE"}

            # 读取脚本元数据（用于自动命名）：NAME（根名）/ label(params)（自定义格式）/ PARAMS（默认值）
            meta = {}
            if namespace.get("NAME"):
                meta["name"] = namespace["NAME"]
            lbl = namespace.get("label")
            if callable(lbl):
                try:
                    meta["label"] = lbl(params)
                except Exception:
                    pass
            if isinstance(namespace.get("PARAMS"), dict):
                meta["params"] = {**namespace["PARAMS"], **(params or {})}

            # 处理返回值
            if isinstance(result, list):
                out = {"values": result}
            elif isinstance(result, dict):
                out = {"values": result.get("values", result.get("data", []))}
                if "lines" in result:
                    out["lines"] = result["lines"]
                if "markers" in result:
                    out["markers"] = result["markers"]
            else:
                out = {"values": [result]}
            out["meta"] = meta
            return out

        finally:
            sys.stdout = old_stdout

    def list_scripts(self) -> list[str]:
        """列出可用的脚本"""
        scripts = []
        for f in self.scripts_dir.rglob("*.py"):
            scripts.append(str(f.relative_to(self.scripts_dir)))
        return sorted(scripts)
