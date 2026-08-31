"""
AgentKline - 业务服务层（可编程核心）
FastAPI 与 MCP server 共用此层，不依赖任何传输协议。
推送事件通过 self.notify 回调注入（FastAPI 注入 WS 广播，MCP 可注入自己的通知或置空）。
"""
import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from .state import StateManager
from .script_engine import ScriptEngine
from .datasource import DataSourceManager

logger = logging.getLogger("agentkline.service")


def _to_ms(v):
    """时间戳秒→毫秒自适应：|v|<1e11 视为秒（epoch_s），×1000；否则视为已是毫秒。"""
    if v is None:
        return None
    v = int(v)
    return v * 1000 if abs(v) < 10**11 else v


class AgentKlineService:
    """AgentKline 业务核心"""

    def __init__(self, scripts_dir: str):
        self.state = StateManager()
        self.script_engine = ScriptEngine(scripts_dir)
        self.datasource = DataSourceManager(self.state, self.script_engine)
        self.notify: Callable[[dict], None] = lambda msg: None  # 由传输层注入
        self.current_view: dict = {}  # 用户当前视图（前端上报）

    # ============ 画板 ============
    def create_board(self, board_id, name=None, intervals=None):
        result = self.state.create_board(board_id, name, intervals)
        if not result.get("error"):
            self._bc({"type": "board_create", "board": result})
        return result

    def list_boards(self):
        return {"boards": self.state.list_boards()}

    def switch_board(self, board_id):
        result = self.state.switch_board(board_id)
        if not result.get("error"):
            tf = self.state.get_default_timeframe(board_id)
            self._bc({"type": "board_switch", "board_id": board_id, "timeframe": tf,
                      "state": self.state.get_timeframe_state(board_id, tf)})
        return result

    def update_board(self, board_id, data):
        return self.state.update_board(board_id, data)

    def delete_board(self, board_id):
        result = self.state.delete_board(board_id)
        if not result.get("error"):
            self._bc({"type": "board_remove", "board_id": board_id,
                      "current_board": self.state.current_board_id})
            # 删除最后一个画板 → 自动补一个空白画板，保证界面永远有画板
            if not self.state.boards:
                created = self.create_board("board_1", "画板")
                self.switch_board(created["id"])
        return result

    # ============ 时间周期 ============
    def create_timeframe(self, board_id, interval):
        result = self.state.create_timeframe(board_id, interval)
        if not result.get("error"):
            self._bc({"type": "timeframe_create", "board_id": board_id, "interval": interval})
        return result

    def delete_timeframe(self, board_id, tf):
        result = self.state.delete_timeframe(board_id, tf)
        if not result.get("error"):
            self._bc({"type": "timeframe_remove", "board_id": board_id, "interval": tf,
                      "default_timeframe": result.get("default_timeframe")})
            # 删除最后一个周期 → 自动补默认 1d，保证画板永远有周期
            board = self.state.boards.get(board_id)
            if board is not None and not board.intervals:
                self.create_timeframe(board_id, "1d")
                self.switch_timeframe(board_id, "1d")
        return result

    def list_timeframes(self, board_id):
        return self.state.list_timeframes(board_id)

    def switch_timeframe(self, board_id, tf):
        result = self.state.switch_timeframe(board_id, tf)
        if not result.get("error"):
            self._bc({"type": "timeframe_switch", "board_id": board_id, "timeframe": tf,
                      "state": self.state.get_timeframe_state(board_id, tf)})
        return result

    # ============ K线 ============
    def set_ohlcv(self, board_id, timeframe, ohlcv, markers=None):
        result = self.state.set_ohlcv(board_id, timeframe, ohlcv, markers)
        if not result.get("error"):
            # 画板级指标自动应用到本周期
            self.state.propagate_board_indicators(board_id, timeframe)
            self.refresh_dynamic_indicators(board_id, timeframe)
            self._bc({"type": "ohlcv_update", "board_id": board_id, "timeframe": timeframe,
                      "data": ohlcv, "markers": markers or []})
        return result

    def set_markers(self, board_id, timeframe, markers):
        markers = list(markers or [])
        dropped = []
        bars = self.state.get_ohlcv(board_id, timeframe)
        if bars:  # 有K线才做范围校验；越界丢弃并回报，不静默吞掉
            lo, hi = bars[0]["timestamp"], bars[-1]["timestamp"]
            kept = []
            for m in markers:
                t = m.get("time")
                if t is not None and lo <= t <= hi:
                    kept.append(m)
                else:
                    dropped.append({"time": t, "reason": "out_of_range"})
            markers = kept
        result = self.state.set_markers(board_id, timeframe, markers)
        if not result.get("error"):
            self._bc({"type": "markers_update", "board_id": board_id, "timeframe": timeframe,
                      "markers": markers})
            if dropped:
                result["dropped"] = dropped
        return result

    def load_csv(self, board_id, timeframe, path, time_col="timestamp"):
        try:
            ohlcv = self._parse_csv(path, time_col)
        except Exception as e:
            return {"error": f"CSV parse error: {e}"}
        return self.set_ohlcv(board_id, timeframe, ohlcv)

    # ============ 指标 ============
    def add_indicator(self, board_id, timeframe, name, values=None, subplot=None,
                      style=None, type=None, markers=None, lines=None, replace=True,
                      script=None, params=None, scope="board", display_name=None):
        """加指标（统一入口）。
        - 给 script：计算型 → 委托 run_script(save_as=indicator) 执行脚本得出值
        - 给 values/lines：现成型 → 直接落值
        - 两者皆无：返回 400 空指标错误"""
        if script:
            return self.run_script(board_id, timeframe, script, params, save_as="indicator",
                                   indicator_name=name, subplot=subplot, scope=scope,
                                   display_name=display_name)
        if values is None and not lines:
            return {"error": "EMPTY_INDICATOR: 需要 script（计算型）或 values/lines（现成型）"}
        existing = self.state.get_indicator(board_id, timeframe, name)
        if existing and not replace:
            return {"error": "INDICATOR_EXISTS"}
        result = self.state.set_indicator(board_id, timeframe, name, values=values,
                                          subplot=subplot, style=style, type=type,
                                          markers=markers, lines=lines)
        if not result.get("error"):
            self._bc({"type": "indicator_update" if existing else "indicator_add",
                      "board_id": board_id, "timeframe": timeframe, "name": name,
                      "values": values, "subplot": subplot, "style": style,
                      "indicator_type": type, "markers": markers, "lines": lines})
        return result

    def run_script(self, board_id, timeframe, path, params=None, save_as=None,
                   indicator_name=None, subplot=None, scope="board", display_name=None):
        """通用脚本执行。save_as: ohlcv / indicator / None。
        scope(仅 indicator): board=作用于所有周期(默认) / timeframe=仅本周期"""
        params = params or {}
        if save_as == "indicator":
            name = indicator_name or Path(path).stem

            if scope == "board":
                # 画板级：注册定义 + 在所有周期注册并按各自K线计算
                self.state.register_board_indicator(board_id, name, path, params, subplot)
                for tf in self._all_timeframes(board_id):
                    if subplot:
                        self._ensure_subplot(board_id, tf, subplot)
                    self.state.propagate_board_indicators(board_id, tf)
                    self.refresh_dynamic_indicators(board_id, tf)
                cur = self.state.get_indicator(board_id, timeframe, name)
                if display_name:
                    self._set_display(board_id, timeframe, name, path, params, None, override=display_name)
                self._bc({"type": "indicator_add", "board_id": board_id, "timeframe": timeframe,
                          "name": name, "values": (cur or {}).get("values"),
                          "lines": (cur or {}).get("lines"), "subplot": subplot,
                          "params": (cur or {}).get("params"),
                          "display_name": (cur or {}).get("display_name"), "scope": "board"})
                return {"status": "ok", "save_as": "indicator", "name": name, "scope": "board"}

            # 本周期
            ohlcv = self.state.get_ohlcv(board_id, timeframe)
            if not ohlcv:
                return {"error": "No OHLCV data loaded. Load data first."}
            result = self.script_engine.run_indicator_script(path, ohlcv, params)
            if result.get("error"):
                return result
            values = result.get("values", [])
            lines = result.get("lines")
            eff_params = (result.get("meta") or {}).get("params", params)
            if subplot:
                self._ensure_subplot(board_id, timeframe, subplot)
            self.state.set_indicator(board_id, timeframe, name,
                                     values=values if not lines else None,
                                     lines=lines, markers=result.get("markers"),
                                     subplot=subplot, script_path=path, params=eff_params,
                                     scope="timeframe")
            self.state.register_dynamic_indicator(board_id, timeframe, name, path, eff_params)
            self._set_display(board_id, timeframe, name, path, eff_params, result.get("meta"),
                              override=display_name)
            self._bc({"type": "indicator_add", "board_id": board_id, "timeframe": timeframe,
                      "name": name, "values": values if not lines else None,
                      "lines": lines, "markers": result.get("markers"), "subplot": subplot,
                      "params": eff_params,
                      "display_name": (self.state.get_indicator(board_id, timeframe, name) or {}).get("display_name"),
                      "scope": "timeframe"})
            return {"status": "ok", "save_as": "indicator", "name": name,
                    "count": len(values) if not lines else len(lines), "scope": "timeframe"}
        else:
            result = self.script_engine.run_script(path, params)
            if result.get("error"):
                return result
            data = result.get("data")
            if not data:
                return {"status": "ok", "output": result.get("output")}
            if save_as == "ohlcv":
                r = self.set_ohlcv(board_id, timeframe, data)
                return {"status": "ok", "save_as": "ohlcv", "count": len(data), **r}
            return {"status": "ok", "data": data}

    def delete_indicator(self, board_id, timeframe, name):
        is_board = any(i["name"] == name for i in self.state.get_board_indicators(board_id))
        if is_board:
            # 画板级：从画板定义 + 所有周期移除
            self.state.remove_board_indicator(board_id, name)
            for tf in self._all_timeframes(board_id):
                self.state.remove_dynamic_indicator(board_id, tf, name)
                self.state.delete_indicator(board_id, tf, name)
            self._bc({"type": "indicator_remove", "board_id": board_id,
                      "timeframe": timeframe, "name": name})
            return {"status": "ok"}

        result = self.state.delete_indicator(board_id, timeframe, name)
        if not result.get("error"):
            self._bc({"type": "indicator_remove", "board_id": board_id,
                      "timeframe": timeframe, "name": name})
        return result

    def refresh_indicator(self, board_id, timeframe, name):
        indicator = self.state.get_indicator(board_id, timeframe, name)
        if not indicator:
            return {"error": "Indicator not found"}
        if not indicator.get("script_path"):
            return {"error": "Indicator has no script"}
        ohlcv = self.state.get_ohlcv(board_id, timeframe)
        result = self.script_engine.run_indicator_script(indicator["script_path"], ohlcv,
                                                        indicator.get("params", {}))
        if result.get("error"):
            return result
        self.state.set_indicator(board_id, timeframe, name, values=result["values"])
        self._set_display(board_id, timeframe, name, indicator["script_path"],
                          indicator.get("params", {}), result.get("meta"))
        self._bc({"type": "indicator_refresh", "board_id": board_id, "timeframe": timeframe,
                  "name": name, "values": result["values"], "subplot": indicator.get("subplot"),
                  "display_name": (self.state.get_indicator(board_id, timeframe, name) or {}).get("display_name")})
        return {"status": "ok", "name": name}

    # ============ 指标自动命名 + 统一更新 ============
    def _auto_display(self, path, params, meta):
        """根名优先级：脚本 label() > 脚本 NAME > 文件名 stem；再拼参数值"""
        meta = meta or {}
        if meta.get("label"):
            return meta["label"]
        root = (meta.get("name") or Path(path).stem).upper()
        vals = [str(v) for v in (params or {}).values()]
        if len(vals) > 3:
            vals = vals[:3] + ['…']  # 参数过多时截断，完整信息在设置弹窗
        return f"{root}({', '.join(vals)})" if vals else root

    def _set_display(self, board_id, tf, name, path, params, meta, override=None):
        ind = self.state.get_indicator(board_id, tf, name) or {}
        if override:
            self.state.set_indicator(board_id, tf, name, display_name=override, custom_label=True)
        elif not ind.get("custom_label"):
            self.state.set_indicator(board_id, tf, name,
                                     display_name=self._auto_display(path, params, meta))

    def update_indicator(self, board_id, timeframe, name, params=None, style=None,
                         lines_style=None, display_name=None, auto_label=None):
        """统一更新：改参数→重算；改样式→不重算；可改显示名/恢复自动命名。
        画板级指标会同步到所有周期。"""
        indicator = self.state.get_indicator(board_id, timeframe, name)
        if not indicator:
            return {"error": "Indicator not found"}
        is_board = any(i["name"] == name for i in self.state.get_board_indicators(board_id))
        targets = self._all_timeframes(board_id) if is_board else [timeframe]

        # 恢复自动命名
        if auto_label:
            for tf in targets:
                self.state.set_indicator(board_id, tf, name, custom_label=False, display_name=None)

        # 改样式（不重算）：style=单线整体；lines_style=按线名逐线覆盖
        if style is not None or lines_style:
            for tf in targets:
                ind = self.state.get_indicator(board_id, tf, name) or {}
                if lines_style and ind.get("lines"):
                    newlines = []
                    for ln in ind["lines"]:
                        ls = dict(ln.get("style") or {})
                        ls.update(lines_style.get(ln.get("name"), {}) or {})
                        newlines.append({**ln, "style": ls})
                    self.state.set_indicator(board_id, tf, name, lines=newlines)
                if style is not None:
                    self.state.set_indicator(board_id, tf, name, style=style)

        # 改参数（重算）或仅改名
        if params is not None:
            if not indicator.get("script_path"):
                return {"error": "Indicator has no script, cannot change params"}
            for tf in targets:
                ohlcv = self.state.get_ohlcv(board_id, tf)
                if not ohlcv:
                    continue
                merged = {**(indicator.get("params") or {}), **params}
                result = self.script_engine.run_indicator_script(indicator["script_path"], ohlcv, merged)
                if result.get("error"):
                    return result
                lines = result.get("lines")
                self.state.set_indicator(board_id, tf, name,
                                         values=result.get("values") if not lines else None,
                                         lines=lines, markers=result.get("markers"),
                                         params=merged)
                self._set_display(board_id, tf, name, indicator["script_path"], merged,
                                  result.get("meta"), override=display_name)
                self._bc({"type": "indicator_update", "board_id": board_id, "timeframe": tf,
                          "name": name, "values": result.get("values") if not lines else None,
                          "lines": lines, "subplot": indicator.get("subplot"),
                          "style": style, "params": merged, "scope": "board" if is_board else None})
        else:
            # 未改参数：只更新显示名
            for tf in targets:
                self._set_display(board_id, tf, name, indicator.get("script_path"),
                                  indicator.get("params"), None, override=display_name)

        # 广播样式/命名刷新（前端重渲染）
        cur = self.state.get_indicator(board_id, timeframe, name)
        self._bc({"type": "indicator_update", "board_id": board_id, "timeframe": timeframe,
                  "name": name, "values": cur.get("values"), "lines": cur.get("lines"),
                  "subplot": cur.get("subplot"), "style": cur.get("style"),
                  "params": cur.get("params"),
                  "display_name": cur.get("display_name"), "scope": "board" if is_board else None})
        return {"status": "ok", "name": name, "display_name": cur.get("display_name")}

    # ============ 划线 drawings ============
    def add_drawing(self, board_id, timeframe, drawing):
        result = self.state.add_drawing(board_id, timeframe, drawing)
        if not result.get("error"):
            self._bc({"type": "drawing_add", "board_id": board_id, "timeframe": timeframe,
                      "drawing": result["drawing"]})
        return result

    def delete_drawing(self, board_id, timeframe, drawing_id):
        result = self.state.delete_drawing(board_id, timeframe, drawing_id)
        if not result.get("error"):
            self._bc({"type": "drawing_remove", "board_id": board_id, "timeframe": timeframe,
                      "id": drawing_id})
        return result

    def update_drawing(self, board_id, timeframe, drawing_id, patch):
        result = self.state.update_drawing(board_id, timeframe, drawing_id, patch)
        if not result.get("error"):
            self._bc({"type": "drawing_update", "board_id": board_id, "timeframe": timeframe,
                      "drawing": result["drawing"]})
        return result

    def list_drawings(self, board_id, timeframe):
        return {"drawings": self.state.list_drawings(board_id, timeframe)}

    # ============ 区间只读（默认当前 view，秒→毫秒自适应） ============
    def _resolve_range(self, board_id, timeframe, start, end):
        """返回 (ohlcv, i0, i1)；不传 start/end 默认当前 view 窗口。"""
        ohlcv = self.state.get_ohlcv(board_id, timeframe)
        if not ohlcv:
            return None, 0, -1
        start = _to_ms(start)
        end = _to_ms(end)
        n = len(ohlcv)
        if start is None and end is None:
            view = self.current_view
            if view and view.get("board_id") == board_id and view.get("timeframe") == timeframe \
                    and view.get("from_time") and view.get("to_time"):
                start, end = view["from_time"], view["to_time"]
        i0, i1 = 0, n - 1
        if start is not None:
            i0 = next((i for i, b in enumerate(ohlcv) if b["timestamp"] >= start), 0)
        if end is not None:
            i1 = next((i for i in range(n - 1, -1, -1) if ohlcv[i]["timestamp"] <= end), n - 1)
        return ohlcv, i0, i1

    def get_kline(self, board_id, timeframe, start=None, end=None):
        """纯 K 线（含成交量）区间切片；不传范围=当前 view。"""
        ohlcv, i0, i1 = self._resolve_range(board_id, timeframe, start, end)
        if not ohlcv:
            return {"error": "No data"}
        sliced = ohlcv[i0:i1 + 1]
        tf_state = self.state.get_board(board_id).get_tf(timeframe)
        return {
            "board_id": board_id, "timeframe": timeframe, "symbol": tf_state.symbol,
            "range": {"from": sliced[0]["timestamp"] if sliced else None,
                      "to": sliced[-1]["timestamp"] if sliced else None},
            "ohlcv": sliced,
        }

    def get_indicators(self, board_id, timeframe, start=None, end=None, names=None):
        """指标值区间切片，范围逻辑同 get_kline；names 指定一个/多个指标，默认全部。"""
        ohlcv, i0, i1 = self._resolve_range(board_id, timeframe, start, end)
        if not ohlcv:
            return {"error": "No data"}
        tf_state = self.state.get_board(board_id).get_tf(timeframe)
        wanted = set(names) if names else None
        indicators = {}
        for name, ind in tf_state.indicators.items():
            if wanted is not None and name not in wanted:
                continue
            if ind.get("lines"):
                indicators[name] = {"lines": [
                    {"name": l.get("name"), "type": l.get("type"),
                     "values": (l.get("values") or [])[i0:i1 + 1]}
                    for l in ind["lines"]]}
            else:
                indicators[name] = {"values": (ind.get("values") or [])[i0:i1 + 1]}
        return {"board_id": board_id, "timeframe": timeframe,
                "range": {"from": ohlcv[i0]["timestamp"] if i0 <= i1 else None,
                          "to": ohlcv[i1]["timestamp"] if i0 <= i1 else None},
                "indicators": indicators}

    def get_markers(self, board_id, timeframe):
        """读取主图标记。"""
        board = self.state.get_board(board_id)
        tf_state = board.get_tf(timeframe) if board else None
        if not tf_state:
            return {"error": "No such board/timeframe"}
        return {"board_id": board_id, "timeframe": timeframe, "markers": tf_state.markers}

    def get_overview(self, board_id, timeframe):
        """轻量结构总览：只回结构与计数，不回 K 线/指标数值数组（省 token）。"""
        board = self.state.get_board(board_id)
        tf_state = board.get_tf(timeframe) if board else None
        if not tf_state:
            return {"error": "No such board/timeframe"}
        ind_meta = {}
        for name, ind in tf_state.indicators.items():
            ind_meta[name] = {
                "type": ind.get("type"), "subplot": ind.get("subplot"),
                "display_name": ind.get("display_name"), "params": ind.get("params"),
                "kind": "lines" if ind.get("lines") else "values",
                "dynamic": bool(ind.get("script_path")),
            }
        view = self.current_view if (self.current_view
                                     and self.current_view.get("board_id") == board_id
                                     and self.current_view.get("timeframe") == timeframe) else None
        return {
            "board_id": board_id, "timeframe": timeframe,
            "symbol": tf_state.symbol, "interval": tf_state.interval,
            "last_updated": tf_state.last_updated, "bars": len(tf_state.ohlcv),
            "view": {"from_time": view.get("from_time"), "to_time": view.get("to_time")} if view else None,
            "datasource": self.datasource.get(board_id, timeframe),
            "indicators": ind_meta,
            "subplots": [s.get("name") for s in tf_state.subplots.values()],
            "markers_count": len(tf_state.markers),
            "drawings_count": len(tf_state.drawings),
        }

    def set_view_range(self, board_id, timeframe, from_time, to_time):
        """让前端聚焦到指定时间窗口（AI 主动把画面拉到某段时间，如回测亏损区间）。
        写入 current_view 并广播 view_set；前端仅在当前显示的板/周期上应用。"""
        board = self.state.get_board(board_id)
        tf_state = board.get_tf(timeframe) if board else None
        if not tf_state:
            return {"error": "No such board/timeframe"}
        from_time = _to_ms(from_time)
        to_time = _to_ms(to_time)
        if from_time is None or to_time is None or from_time >= to_time:
            return {"error": "Invalid range: need from < to"}
        self.current_view = {"board_id": board_id, "timeframe": timeframe,
                             "from_time": from_time, "to_time": to_time,
                             "updated_at": datetime.now().isoformat()}
        self._bc({"type": "view_set", "board_id": board_id, "timeframe": timeframe,
                  "from_time": from_time, "to_time": to_time})
        return {"status": "ok", "board_id": board_id, "timeframe": timeframe,
                "from_time": from_time, "to_time": to_time}

    def create_subplot(self, board_id, timeframe, name, height=150, title=None):
        result = self.state.create_subplot(board_id, timeframe, name, height, title)
        if not result.get("error"):
            self._bc({"type": "subplot_create", "board_id": board_id, "timeframe": timeframe,
                      "name": name, "height": height, "title": title})
        return result

    def update_subplot(self, board_id, timeframe, name, height=None, title=None):
        result = self.state.update_subplot(board_id, timeframe, name, height, title)
        if not result.get("error"):
            self._bc({"type": "subplot_update", "board_id": board_id, "timeframe": timeframe,
                      "name": name, "height": result.get("height"), "title": result.get("title")})
        return result

    def delete_subplot(self, board_id, timeframe, name):
        result = self.state.delete_subplot(board_id, timeframe, name)
        if not result.get("error"):
            self._bc({"type": "subplot_remove", "board_id": board_id, "timeframe": timeframe,
                      "name": name})
        return result

    def list_subplots(self, board_id, timeframe):
        return {"subplots": self.state.list_subplots(board_id, timeframe)}

    # ============ 数据源 ============
    def set_datasource(self, board_id, tf, path, params=None, poll_interval=None, indicators=None):
        # 停止旧数据源
        import asyncio
        self.datasource.stop(board_id, tf)

        result = self.script_engine.run_script(path, params or {})
        if result.get("error"):
            return result

        data = result.get("data", [])
        self.state.set_ohlcv(board_id, tf, data)

        if indicators:
            for ind in indicators:
                self.state.register_dynamic_indicator(board_id, tf, ind["name"],
                                                      ind["path"], ind.get("params", {}))
        self.refresh_dynamic_indicators(board_id, tf)

        self.datasource.set_config(board_id, tf, path, params, poll_interval)
        if poll_interval and poll_interval > 0:
            self.datasource.start(board_id, tf, path, params, poll_interval)

        self._bc({"type": "datasource_start", "board_id": board_id, "timeframe": tf,
                  "poll_interval": poll_interval})
        self._bc({"type": "ohlcv_update", "board_id": board_id, "timeframe": tf,
                  "data": data, "markers": []})
        return {"status": "ok", "count": len(data)}

    def get_datasource(self, board_id, tf):
        return {"datasource": self.datasource.get(board_id, tf)}

    def delete_datasource(self, board_id, tf):
        self.datasource.stop(board_id, tf)
        self._bc({"type": "datasource_stop", "board_id": board_id, "timeframe": tf})
        return {"status": "ok"}

    def refresh_timeframe(self, board_id, tf):
        ds = self.datasource.get(board_id, tf)
        if ds and ds.get("path"):
            result = self.script_engine.run_script(ds["path"], ds.get("params", {}))
            if not result.get("error"):
                self.state.set_ohlcv(board_id, tf, result.get("data", []))
        self.refresh_dynamic_indicators(board_id, tf)
        return {"status": "ok"}

    def load_history(self, board_id, tf, limit=200):
        ds = self.datasource.get(board_id, tf)
        if not ds or not ds.get("path"):
            return {"prepended": 0, "error": "No datasource configured"}
        ohlcv = self.state.get_ohlcv(board_id, tf)
        if not ohlcv:
            return {"prepended": 0}
        earliest = ohlcv[0]["timestamp"]
        params = dict(ds.get("params", {}))
        params["until"] = earliest
        params["limit"] = limit
        result = self.script_engine.run_script(ds["path"], params)
        if result.get("error"):
            return {"prepended": 0, "error": result["error"]}
        older = [b for b in result.get("data", []) if b["timestamp"] < earliest]
        if not older:
            return {"prepended": 0}
        older.sort(key=lambda b: b["timestamp"])
        new_ohlcv = older + ohlcv
        markers = self.state.get_timeframe_state(board_id, tf).get("markers", [])
        self.state.set_ohlcv(board_id, tf, new_ohlcv, markers)
        self._bc({"type": "ohlcv_update", "board_id": board_id, "timeframe": tf,
                  "data": new_ohlcv, "markers": markers, "prepended": len(older)})
        self.refresh_dynamic_indicators(board_id, tf)
        return {"prepended": len(older), "total": len(new_ohlcv)}

    # ============ 状态 ============
    def get_state(self, board_id, timeframe):
        return self.state.get_timeframe_state(board_id, timeframe)

    def get_full_state(self, board_id):
        return self.state.get_full_state(board_id)

    # ============ 内部 ============
    def _all_timeframes(self, board_id):
        board = self.state.get_board(board_id)
        return list(board.timeframes.keys()) if board else []

    def _ensure_subplot(self, board_id, tf, subplot):
        if not subplot:
            return
        board = self.state.get_board(board_id)
        tf_state = board.get_tf(tf) if board else None
        if tf_state and subplot not in tf_state.subplots:
            self.state.create_subplot(board_id, tf, subplot, 150, subplot)

    def _bc(self, message):
        try:
            self.notify(message)
        except Exception as e:
            logger.debug(f"notify error: {e}")

    def refresh_dynamic_indicators(self, board_id, timeframe):
        ohlcv = self.state.get_ohlcv(board_id, timeframe)
        if not ohlcv:
            return
        for ind in self.state.get_dynamic_indicators(board_id, timeframe):
            result = self.script_engine.run_indicator_script(ind["path"], ohlcv, ind.get("params", {}))
            if not result.get("error"):
                lines = result.get("lines")
                values = result.get("values")
                if lines or values:
                    is_board = any(b["name"] == ind["name"]
                                   for b in self.state.get_board_indicators(board_id))
                    eff = (result.get("meta") or {}).get("params", ind.get("params", {}))
                    self.state.set_indicator(board_id, timeframe, ind["name"],
                                             values=values if not lines else None,
                                             lines=lines, markers=result.get("markers"),
                                             subplot=ind.get("subplot"), params=eff,
                                             scope="board" if is_board else None)
                    self._set_display(board_id, timeframe, ind["name"], ind["path"],
                                      eff, result.get("meta"))
                    self._bc({"type": "indicator_refresh", "board_id": board_id,
                              "timeframe": timeframe, "name": ind["name"],
                              "values": values if not lines else None,
                              "lines": lines, "subplot": ind.get("subplot"),
                              "display_name": (self.state.get_indicator(board_id, timeframe, ind["name"]) or {}).get("display_name")})

    @staticmethod
    def _parse_csv(path, time_col="timestamp"):
        ohlcv = []
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                time_val = row.get(time_col, row.get("timestamp", row.get("time", "")))
                if isinstance(time_val, str):
                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y%m%d"]:
                        try:
                            dt = datetime.strptime(time_val, fmt)
                            time_val = int(dt.timestamp() * 1000)
                            break
                        except ValueError:
                            continue
                    else:
                        time_val = int(time_val)
                else:
                    time_val = int(time_val)
                ohlcv.append({
                    "timestamp": time_val,
                    "open": float(row.get("open", row.get("Open", 0))),
                    "high": float(row.get("high", row.get("High", 0))),
                    "low": float(row.get("low", row.get("Low", 0))),
                    "close": float(row.get("close", row.get("Close", 0))),
                    "volume": float(row.get("volume", row.get("Volume", 0)))
                })
        return ohlcv
