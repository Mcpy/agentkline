"""
AgentKline - 脚本执行引擎（v0.4 R1）

- 双根存储：builtin = <package>/resources/scripts/{datasource,indicator,strategy}（随包发布，只读）
             custom = <scripts_dir>/{...}（可写；save_script 只落这里）
- id = kind/stem 是唯一技术标识；引用格式 kind/name（如 indicator/macd），裸文件名硬切报错
- 元数据 NAME/DESC/PARAMS/CAPS/IDENTITY 为模块顶层**字面常量**，ast 静态抽取（列目录永不 exec）+ mtime 缓存
- CAPS 一致性：声明 ⇒ 必须实现（backfill⇒main 含 until 参；symbols⇒def list_symbols；ticker⇒def ticker），否则 CAPS_MISMATCH；
  不声明 = 无能力（custom 旧脚本缺 CAPS 仅 warning）
- 运行模式 poll/once 是槽位配置属性，不是脚本类别（见 service/datasource）
- L1 沙箱：直接 exec 隔离命名空间（内部调试用），脚本需自律
"""
import ast
import sys
import io
import re
import logging
import inspect
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agentkline.script")

KINDS = ("datasource", "indicator", "strategy")
CAPS_KEYS = ("backfill", "symbols", "ticker")
STEM_RE = re.compile(r"^[a-z0-9_]+$")
META_NAMES = ("NAME", "DESC", "PARAMS", "CAPS", "IDENTITY", "INTERVALS")
SAVE_WARN_BYTES = 100_000  # save_script 大小告警阈值（R8 护栏族）


def parse_id(ref) -> Optional[tuple]:
    """解析 id=kind/stem；非法返回 None"""
    if not isinstance(ref, str):
        return None
    parts = ref.split("/")
    if len(parts) != 2:
        return None
    kind, stem = parts
    if kind not in KINDS or not STEM_RE.match(stem):
        return None
    return kind, stem


def id_error(ref) -> str:
    if isinstance(ref, str) and "/" not in ref:
        return (f"SCRIPT_BAD_ID: '{ref}' 裸文件名已废弃（v0.4 硬切），"
                f"请用 kind/name 格式（如 indicator/macd），kind∈{list(KINDS)}")
    return f"SCRIPT_BAD_ID: '{ref}' 非合法 id（kind/name，stem 需匹配 [a-z0-9_]+）"


class ScriptEngine:
    """Python 脚本执行引擎（双根 + ast 元数据 + 保存即校验）"""

    def __init__(self, custom_dir: str):
        self.custom_root = Path(custom_dir)
        self.builtin_root = Path(__file__).resolve().parent.parent / "resources" / "scripts"
        for root in (self.custom_root, self.builtin_root):
            for k in KINDS:
                (root / k).mkdir(parents=True, exist_ok=True)
        self._cache: dict = {}  # path -> (mtime, meta)

    # ---------- 解析 ----------
    def roots(self):
        return (("custom", self.custom_root), ("builtin", self.builtin_root))

    def resolve(self, ref: str) -> Optional[dict]:
        """id → {id,kind,stem,path,source}；custom 优先（shadow）"""
        parsed = parse_id(ref)
        if not parsed:
            return None
        kind, stem = parsed
        for source, root in self.roots():
            p = root / kind / f"{stem}.py"
            if p.exists():
                return {"id": f"{kind}/{stem}", "kind": kind, "stem": stem,
                        "path": p, "source": source}
        return None

    # ---------- ast 元数据 ----------
    @staticmethod
    def _meta_from_tree(tree) -> dict:
        meta = {"name": None, "desc": ast.get_docstring(tree), "params": {},
                "caps": {k: False for k in CAPS_KEYS}, "caps_declared": False,
                "identity": [], "defs": set(), "main_until": False, "has_main": False}
        literals = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id in META_NAMES:
                        try:
                            literals[t.id] = ast.literal_eval(node.value)
                        except Exception:
                            literals[t.id] = None  # 非字面 = 未声明（契约要求字面）
        if isinstance(literals.get("NAME"), str):
            meta["name"] = literals["NAME"]
        if isinstance(literals.get("DESC"), str):
            meta["desc"] = literals["DESC"]
        if isinstance(literals.get("PARAMS"), dict):
            meta["params"] = literals["PARAMS"]
        caps_raw = literals.get("CAPS")
        if isinstance(caps_raw, dict):
            meta["caps"] = {k: bool(caps_raw.get(k, False)) for k in CAPS_KEYS}
            meta["caps_declared"] = True
        ident = literals.get("IDENTITY")
        if isinstance(ident, list):
            meta["identity"] = [str(x) for x in ident]
        intervals = literals.get("INTERVALS")
        # 支持周期表（字面 list，如 ["15m","1h","4h","1d","1w"]）；不声明=离线源/自由槽
        meta["intervals"] = [str(x) for x in intervals] if isinstance(intervals, list) else None
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                meta["defs"].add(node.name)
                if node.name == "main":
                    meta["has_main"] = True
                    meta["main_until"] = "until" in [a.arg for a in node.args.args]
        return meta

    def _ast_info(self, path: Path) -> dict:
        mtime = path.stat().st_mtime
        hit = self._cache.get(str(path))
        if hit and hit[0] == mtime:
            return hit[1]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        meta = self._meta_from_tree(tree)
        self._cache[str(path)] = (mtime, meta)
        return meta

    def metadata(self, ref: str) -> dict:
        r = self.resolve(ref)
        if not r:
            return {"error": id_error(ref) if parse_id(ref) is None
                    else f"SCRIPT_NOT_FOUND: {ref}"}
        return self._ast_info(r["path"])

    @staticmethod
    def check_caps(meta: dict) -> Optional[str]:
        caps, probs = meta["caps"], []
        if caps["backfill"] and not meta["main_until"]:
            probs.append("CAPS.backfill=True 但 main 签名缺 until 参数")
        if caps["symbols"] and "list_symbols" not in meta["defs"]:
            probs.append("CAPS.symbols=True 但未定义 list_symbols")
        if caps["ticker"] and "ticker" not in meta["defs"]:
            probs.append("CAPS.ticker=True 但未定义 ticker")
        return ("CAPS_MISMATCH: " + "; ".join(probs)) if probs else None

    def caps(self, ref: str) -> dict:
        r = self.resolve(ref)
        if not r:
            return {k: False for k in CAPS_KEYS}
        return self._ast_info(r["path"])["caps"]

    # ---------- 列表 ----------
    def list_scripts(self) -> list:
        seen, out = set(), []
        for source, root in self.roots():
            for kind in KINDS:
                for p in sorted((root / kind).glob("*.py")):
                    sid = f"{kind}/{p.stem}"
                    if sid in seen:
                        continue  # custom shadow builtin
                    seen.add(sid)
                    meta = self._ast_info(p)
                    if not meta["caps_declared"] and source == "custom":
                        logger.warning("脚本 %s 未声明 CAPS（v0.4 硬切后视为无能力）", sid)
                    out.append({
                        "id": sid, "kind": kind, "source": source,
                        "display": meta["name"] or p.stem,
                        "desc": meta["desc"] or "",
                        "params": meta["params"], "caps": meta["caps"],
                        "identity": meta["identity"], "intervals": meta["intervals"],
                    })
        return out

    # ---------- 执行 ----------
    def run_script(self, ref: str, params: dict = None, until=None) -> dict:
        """数据源/通用脚本：main(params[, until]) → {"data": [...]}"""
        r = self.resolve(ref)
        if not r:
            return {"error": id_error(ref) if parse_id(ref) is None
                    else f"SCRIPT_NOT_FOUND: {ref}"}
        meta = self._ast_info(r["path"])
        caps_err = self.check_caps(meta)
        if caps_err:
            return {"error": caps_err}
        try:
            code = r["path"].read_text(encoding="utf-8")
        except Exception as e:
            return {"error": f"SCRIPT_READ_ERROR: {e}"}
        try:
            return self._exec_script(code, params or {}, str(r["path"]), meta, until)
        except Exception as e:
            logger.error("Script execution error: %s: %s", ref, e)
            return {"error": f"SCRIPT_EXEC_ERROR: {e}"}

    def run_indicator_script(self, ref: str, ohlcv: list, params: dict = None) -> dict:
        """指标脚本：main(params, ohlcv) → {"values"/"lines"/"markers", "meta"}"""
        r = self.resolve(ref)
        if not r:
            return {"error": id_error(ref) if parse_id(ref) is None
                    else f"SCRIPT_NOT_FOUND: {ref}"}
        try:
            code = r["path"].read_text(encoding="utf-8")
        except Exception as e:
            return {"error": f"SCRIPT_READ_ERROR: {e}"}
        try:
            return self._exec_indicator_script(code, params or {}, ohlcv, str(r["path"]))
        except Exception as e:
            logger.error("Indicator script error: %s: %s", ref, e)
            return {"error": f"SCRIPT_EXEC_ERROR: {e}"}

    def _exec_script(self, code: str, params: dict, filepath: str, meta: dict, until=None) -> dict:
        namespace = {"__name__": "__main__", "__file__": filepath, "params": params}
        old_stdout, captured = sys.stdout, io.StringIO()
        sys.stdout = captured
        try:
            exec(code, namespace)
            main_func = namespace.get("main")
            if main_func is None:
                return {"error": "SCRIPT_NO_MAIN: 脚本必须定义 main(params) 函数"}
            kwargs = {}
            if meta["main_until"] and until is not None:
                kwargs["until"] = until
            result = main_func(params, **kwargs)
            if result is None:
                return {"error": "SCRIPT_RETURN_NONE: main() 返回了 None"}
            if isinstance(result, list):
                return {"data": result}
            if isinstance(result, dict):
                return {"data": result.get("data", result)}
            return {"data": result}
        finally:
            sys.stdout = old_stdout
            output = captured.getvalue()
            if output:
                logger.info("Script output: %s", output[:500])

    def _exec_indicator_script(self, code: str, params: dict, ohlcv: list, filepath: str) -> dict:
        namespace = {"__name__": "__main__", "__file__": filepath,
                     "params": params, "ohlcv": ohlcv}
        old_stdout, captured = sys.stdout, io.StringIO()
        sys.stdout = captured
        try:
            exec(code, namespace)
            main_func = namespace.get("main")
            if main_func is None:
                return {"error": "SCRIPT_NO_MAIN: 指标脚本必须定义 main(params, ohlcv) 函数"}
            sig = inspect.signature(main_func)
            result = main_func(params, ohlcv) if len(sig.parameters) >= 2 else main_func(params)
            if result is None:
                return {"error": "SCRIPT_RETURN_NONE"}
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

    # ---------- 标的搜索（CAPS.symbols 门控） ----------
    def list_symbols(self, ref: str, query: str = "") -> dict:
        """调用数据源脚本的 list_symbols(query)；无徽章报 NO_SYMBOLS_CAP"""
        r = self.resolve(ref)
        if not r:
            return {"error": id_error(ref) if parse_id(ref) is None
                    else f"SCRIPT_NOT_FOUND: {ref}"}
        meta = self._ast_info(r["path"])
        if not meta["caps"]["symbols"]:
            return {"error": f"NO_SYMBOLS_CAP: {ref} 未声明 CAPS.symbols，搜不到（可裸输入 @源名 裸符号 直配）"}
        code = r["path"].read_text(encoding="utf-8")
        namespace = {"__name__": "__main__", "__file__": str(r["path"])}
        exec(code, namespace)
        fn = namespace.get("list_symbols")
        if not callable(fn):
            return {"error": f"CAPS_MISMATCH: {ref} 声明 symbols 但无 list_symbols"}
        return {"symbols": fn(query) or []}

    def ticker(self, ref: str, params: dict = None) -> dict:
        """调用数据源脚本的 ticker(params)→quote；无徽章报 NO_TICKER_CAP；键白名单 price/ts/change_pct/extra"""
        r = self.resolve(ref)
        if not r:
            return {"error": id_error(ref) if parse_id(ref) is None
                    else f"SCRIPT_NOT_FOUND: {ref}"}
        meta = self._ast_info(r["path"])
        if not meta["caps"]["ticker"]:
            return {"error": f"NO_TICKER_CAP: {ref} 未声明 CAPS.ticker，无报价能力"}
        code = r["path"].read_text(encoding="utf-8")
        namespace = {"__name__": "__main__", "__file__": str(r["path"])}
        exec(code, namespace)
        fn = namespace.get("ticker")
        if not callable(fn):
            return {"error": f"CAPS_MISMATCH: {ref} 声明 ticker 但无 ticker 函数"}
        q = fn(params or {})
        if not isinstance(q, dict) or not isinstance(q.get("price"), (int, float)):
            return {"error": f"TICKER_BAD_SHAPE: {ref} ticker 返回需含数值 price"}
        out = {"price": float(q["price"]), "ts": int(q.get("ts") or 0)}
        if isinstance(q.get("change_pct"), (int, float)):
            out["change_pct"] = float(q["change_pct"])
        if isinstance(q.get("extra"), dict):
            out["extra"] = q["extra"]
        return {"quote": out}

    def has_batch_ticker(self, ref: str) -> bool:
        r = self.resolve(ref)
        if not r:
            return False
        return "tickers" in (self._ast_info(r["path"]).get("defs") or [])

    def tickers(self, ref: str, params_list: list) -> dict:
        """批量报价（性能②）：脚本可选 tickers(params_list)->[quote]（同序）；
        无实现则回退逐行 ticker。返回 {quotes: [...]} 或 {error}"""
        r = self.resolve(ref)
        if not r:
            return {"error": f"SCRIPT_NOT_FOUND: {ref}"}
        meta = self._ast_info(r["path"])
        if not meta["caps"]["ticker"]:
            return {"error": f"NO_TICKER_CAP: {ref}"}
        code = r["path"].read_text(encoding="utf-8")
        namespace = {"__name__": "__main__", "__file__": str(r["path"])}
        exec(code, namespace)
        fn = namespace.get("tickers")
        if callable(fn):
            raw = fn(params_list)
            if not isinstance(raw, list) or len(raw) != len(params_list):
                return {"error": f"TICKERS_BAD_SHAPE: {ref} tickers 需返回与入参同序列表"}
            quotes = []
            for q in raw:
                if not isinstance(q, dict) or not isinstance(q.get("price"), (int, float)):
                    quotes.append(None)
                    continue
                out = {"price": float(q["price"]), "ts": int(q.get("ts") or 0)}
                if isinstance(q.get("change_pct"), (int, float)):
                    out["change_pct"] = float(q["change_pct"])
                if isinstance(q.get("extra"), dict):
                    out["extra"] = q["extra"]
                quotes.append(out)
            return {"quotes": quotes}
        one = namespace.get("ticker")
        if not callable(one):
            return {"error": f"CAPS_MISMATCH: {ref} 声明 ticker 但无 ticker/tickers"}
        quotes = []
        for pl in params_list:
            q = one(pl)
            quotes.append({"price": float(q["price"]), "ts": int(q.get("ts") or 0),
                           **({"change_pct": float(q["change_pct"])} if isinstance(q.get("change_pct"), (int, float)) else {})})
        return {"quotes": quotes}

    # ---------- 保存（只写 custom，保存即校验） ----------
    def save_script(self, ref: str, code: str) -> dict:
        parsed = parse_id(ref)
        if not parsed:
            return {"error": id_error(ref)}
        kind, stem = parsed
        if not isinstance(code, str) or not code.strip():
            return {"error": "SAVE_EMPTY: code 不能为空"}
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {"error": f"SAVE_SYNTAX: {e}"}
        meta = self._meta_from_tree(tree)
        if not meta["has_main"]:
            return {"error": f"SAVE_NO_MAIN: {kind} 脚本必须定义 main 函数"
                             f"（datasource: main(params[, until])；indicator: main(params, ohlcv)）"}
        caps_err = self.check_caps(meta)
        if caps_err:
            return {"error": caps_err}
        path = self.custom_root / kind / f"{stem}.py"
        warning = None
        size = len(code.encode("utf-8"))
        if size > SAVE_WARN_BYTES:
            warning = (f"脚本较大（{size} bytes）：内嵌数据请留意 max_bars_per_slot 护栏，"
                       f"优先脚本自拉数据（新鲜+可重放）")
        path.write_text(code, encoding="utf-8")
        self._cache.pop(str(path), None)
        logger.info("save_script: %s → %s", ref, path)
        out = {"ok": True, "id": f"{kind}/{stem}", "source": "custom", "path": str(path)}
        if warning:
            out["warning"] = warning
        return out
