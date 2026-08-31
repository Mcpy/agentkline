"""
AgentKline - 内存状态管理
管理画板、时间周期、K线、指标、副图
"""
import math
from typing import Optional
from datetime import datetime


def _clean(obj):
    """NaN/Inf -> None，防止非法 JSON 破坏前端 JSON.parse。递归处理 list/dict。"""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


class TimeframeState:
    """单个时间周期的完整状态"""

    def __init__(self, interval: str):
        self.interval = interval
        self.ohlcv: list[dict] = []
        self.markers: list[dict] = []
        self.indicators: dict[str, dict] = {}  # name -> indicator data
        self.subplots: dict[str, dict] = {}    # name -> subplot config
        self.dynamic_indicators: list[dict] = []  # 动态指标（K线更新时自动重算）
        self.drawings: dict[str, dict] = {}    # id -> drawing (划线)
        self.symbol: str = ""
        self.last_updated: str = ""


class Board:
    """单个画板"""

    def __init__(self, board_id: str, name: str = None, intervals: list[str] = None):
        self.id = board_id
        self.name = name or board_id
        self.intervals = intervals or ["1d"]
        self.current_timeframe = self.intervals[0] if self.intervals else "1d"
        self.timeframes: dict[str, TimeframeState] = {}
        for iv in self.intervals:
            self.timeframes[iv] = TimeframeState(iv)
        # 画板级指标定义（scope=board，作用于所有周期）
        self.board_indicators: dict[str, dict] = {}
        self.created_at = datetime.now().isoformat()

    def get_tf(self, tf: str) -> Optional[TimeframeState]:
        return self.timeframes.get(tf)

    def ensure_tf(self, tf: str) -> TimeframeState:
        if tf not in self.timeframes:
            self.timeframes[tf] = TimeframeState(tf)
        return self.timeframes[tf]


class StateManager:
    """全局状态管理器（内存）"""

    def __init__(self):
        self.boards: dict[str, Board] = {}
        self.current_board_id: Optional[str] = None

    # ========== 画板管理 ==========

    def create_board(self, board_id: str, name: str = None, intervals: list[str] = None) -> dict:
        if board_id in self.boards:
            return {"error": f"Board '{board_id}' already exists"}
        board = Board(board_id, name, intervals)
        self.boards[board_id] = board
        if self.current_board_id is None:
            self.current_board_id = board_id
        return {"id": board_id, "name": board.name, "intervals": board.intervals}

    def list_boards(self) -> list[dict]:
        return [
            {"id": b.id, "name": b.name, "intervals": b.intervals,
             "current_timeframe": b.current_timeframe}
            for b in self.boards.values()
        ]

    def switch_board(self, board_id: str) -> dict:
        if board_id not in self.boards:
            return {"error": f"Board '{board_id}' not found"}
        self.current_board_id = board_id
        return {"id": board_id, "name": self.boards[board_id].name}

    def update_board(self, board_id: str, data: dict) -> dict:
        if board_id not in self.boards:
            return {"error": f"Board '{board_id}' not found"}
        board = self.boards[board_id]
        if "name" in data:
            board.name = data["name"]
        return {"id": board_id, "name": board.name}

    def delete_board(self, board_id: str) -> dict:
        if board_id not in self.boards:
            return {"error": f"Board '{board_id}' not found"}
        del self.boards[board_id]
        if self.current_board_id == board_id:
            self.current_board_id = next(iter(self.boards), None)
        return {"status": "ok"}

    def get_board(self, board_id: str) -> Optional[Board]:
        return self.boards.get(board_id)

    # ========== 时间周期管理 ==========

    def create_timeframe(self, board_id: str, interval: str) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        if interval in board.timeframes:
            return {"error": f"Timeframe '{interval}' already exists"}
        board.timeframes[interval] = TimeframeState(interval)
        board.intervals.append(interval)
        return {"status": "ok", "interval": interval}

    def delete_timeframe(self, board_id: str, tf: str) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        if tf not in board.timeframes:
            return {"error": f"Timeframe '{tf}' not found"}
        del board.timeframes[tf]
        if tf in board.intervals:
            board.intervals.remove(tf)
        if board.current_timeframe == tf:
            board.current_timeframe = board.intervals[0] if board.intervals else None
        return {"status": "ok", "default_timeframe": board.current_timeframe}

    def list_timeframes(self, board_id: str) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        return {"board_id": board_id, "timeframes": board.intervals,
                "current": board.current_timeframe}

    def switch_timeframe(self, board_id: str, tf: str) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        if tf not in board.timeframes:
            return {"error": f"Timeframe '{tf}' not found"}
        board.current_timeframe = tf
        return {"status": "ok", "timeframe": tf}

    def get_default_timeframe(self, board_id: str) -> Optional[str]:
        board = self.boards.get(board_id)
        if board:
            return board.current_timeframe
        return None

    # ========== K线数据 ==========

    def set_ohlcv(self, board_id: str, timeframe: str, ohlcv: list[dict],
                  markers: list[dict] = None) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        tf_state = board.ensure_tf(timeframe)
        tf_state.ohlcv = ohlcv
        if markers is not None:
            tf_state.markers = markers
        tf_state.last_updated = datetime.now().isoformat()
        return {"status": "ok", "count": len(ohlcv)}

    def get_ohlcv(self, board_id: str, timeframe: str) -> list[dict]:
        board = self.boards.get(board_id)
        if not board:
            return []
        tf_state = board.get_tf(timeframe)
        return tf_state.ohlcv if tf_state else []

    def set_markers(self, board_id: str, timeframe: str, markers: list[dict]) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        tf_state = board.ensure_tf(timeframe)
        tf_state.markers = markers
        return {"status": "ok", "count": len(markers)}

    # ========== 指标管理 ==========

    def set_indicator(self, board_id: str, timeframe: str, name: str,
                      values: list = None, subplot: str = None,
                      style: dict = None, type: str = None,
                      markers: list = None, lines: list = None,
                      script_path: str = None, params: dict = None,
                      scope: str = None, display_name: str = None,
                      custom_label: bool = None) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        tf_state = board.ensure_tf(timeframe)
        existing = tf_state.indicators.get(name, {})
        # NaN/Inf 清洗（用户脚本可能产出，避免非法 JSON）
        values = _clean(values)
        lines = _clean(lines)
        markers = _clean(markers)
        # 合并更新：只覆盖非 None 的字段，保留其余（重算时不丢 subplot/style/script_path）
        tf_state.indicators[name] = {
            "name": name,
            "values": values if values is not None else existing.get("values"),
            "subplot": subplot if subplot is not None else existing.get("subplot"),
            "style": style if style is not None else existing.get("style"),
            "type": type if type is not None else existing.get("type"),
            "markers": markers if markers is not None else existing.get("markers"),
            "lines": lines if lines is not None else existing.get("lines"),
            "script_path": script_path if script_path is not None else existing.get("script_path"),
            "params": params if params is not None else existing.get("params"),
            "scope": scope if scope is not None else existing.get("scope"),
            "display_name": display_name if display_name is not None else existing.get("display_name"),
            "custom_label": custom_label if custom_label is not None else existing.get("custom_label", False),
        }
        return {"status": "ok", "name": name}

    def get_indicator(self, board_id: str, timeframe: str, name: str) -> Optional[dict]:
        board = self.boards.get(board_id)
        if not board:
            return None
        tf_state = board.get_tf(timeframe)
        if not tf_state:
            return None
        return tf_state.indicators.get(name)

    def delete_indicator(self, board_id: str, timeframe: str, name: str) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        tf_state = board.get_tf(timeframe)
        if not tf_state:
            return {"error": f"Timeframe '{timeframe}' not found"}
        if name not in tf_state.indicators:
            return {"error": f"Indicator '{name}' not found"}
        del tf_state.indicators[name]
        return {"status": "ok"}

    def register_dynamic_indicator(self, board_id: str, timeframe: str,
                                   name: str, path: str, params: dict = None,
                                   subplot: str = None):
        """注册动态指标（K线更新时自动重算）"""
        board = self.boards.get(board_id)
        if not board:
            return
        tf_state = board.ensure_tf(timeframe)
        # 避免重复注册
        for ind in tf_state.dynamic_indicators:
            if ind["name"] == name:
                ind["path"] = path
                ind["params"] = params or {}
                if subplot is not None:
                    ind["subplot"] = subplot
                return
        tf_state.dynamic_indicators.append({
            "name": name, "path": path, "params": params or {}, "subplot": subplot
        })

    def remove_dynamic_indicator(self, board_id: str, timeframe: str, name: str):
        board = self.boards.get(board_id)
        if not board:
            return
        tf_state = board.get_tf(timeframe)
        if not tf_state:
            return
        tf_state.dynamic_indicators = [i for i in tf_state.dynamic_indicators if i["name"] != name]

    def get_dynamic_indicators(self, board_id: str, timeframe: str) -> list[dict]:
        board = self.boards.get(board_id)
        if not board:
            return []
        tf_state = board.get_tf(timeframe)
        return tf_state.dynamic_indicators if tf_state else []

    # ========== 画板级指标（scope=board，作用于所有周期） ==========

    def register_board_indicator(self, board_id: str, name: str, path: str,
                                 params: dict = None, subplot: str = None):
        """注册画板级指标定义"""
        board = self.boards.get(board_id)
        if not board:
            return
        board.board_indicators[name] = {"name": name, "path": path,
                                        "params": params or {}, "subplot": subplot}

    def get_board_indicators(self, board_id: str) -> list[dict]:
        board = self.boards.get(board_id)
        return list(board.board_indicators.values()) if board else []

    def remove_board_indicator(self, board_id: str, name: str):
        board = self.boards.get(board_id)
        if board and name in board.board_indicators:
            del board.board_indicators[name]

    def propagate_board_indicators(self, board_id: str, timeframe: str):
        """把画板级指标注册到指定周期（使其在该周期被计算）"""
        for ind in self.get_board_indicators(board_id):
            self.register_dynamic_indicator(board_id, timeframe, ind["name"],
                                            ind["path"], ind["params"], ind.get("subplot"))

    # ========== 副图管理 ==========

    def create_subplot(self, board_id: str, timeframe: str, name: str,
                       height: int = 150, title: str = None) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        tf_state = board.ensure_tf(timeframe)
        if name in tf_state.subplots:
            return {"error": f"Subplot '{name}' already exists"}
        tf_state.subplots[name] = {"name": name, "height": height, "title": title}
        return {"status": "ok", "name": name}

    def update_subplot(self, board_id: str, timeframe: str, name: str,
                       height: int = None, title: str = None) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        tf_state = board.get_tf(timeframe)
        if not tf_state or name not in tf_state.subplots:
            return {"error": f"Subplot '{name}' not found"}
        sp = tf_state.subplots[name]
        if height is not None:
            sp["height"] = height
        if title is not None:
            sp["title"] = title
        return sp

    def delete_subplot(self, board_id: str, timeframe: str, name: str) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        tf_state = board.get_tf(timeframe)
        if not tf_state or name not in tf_state.subplots:
            return {"error": f"Subplot '{name}' not found"}
        del tf_state.subplots[name]
        # 同时删除该副图上的所有指标
        to_remove = [k for k, v in tf_state.indicators.items() if v.get("subplot") == name]
        for k in to_remove:
            del tf_state.indicators[k]
        return {"status": "ok"}

    def list_subplots(self, board_id: str, timeframe: str) -> list[dict]:
        board = self.boards.get(board_id)
        if not board:
            return []
        tf_state = board.get_tf(timeframe)
        if not tf_state:
            return []
        return list(tf_state.subplots.values())

    # ========== 划线 drawings ==========

    def add_drawing(self, board_id: str, timeframe: str, drawing: dict) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        tf_state = board.ensure_tf(timeframe)
        import uuid
        did = drawing.get("id") or uuid.uuid4().hex[:8]
        drawing = {**drawing, "id": did}
        tf_state.drawings[did] = drawing
        return {"status": "ok", "id": did, "drawing": drawing}

    def delete_drawing(self, board_id: str, timeframe: str, drawing_id: str) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        tf_state = board.get_tf(timeframe)
        if not tf_state or drawing_id not in tf_state.drawings:
            return {"error": f"Drawing '{drawing_id}' not found"}
        del tf_state.drawings[drawing_id]
        return {"status": "ok"}

    def update_drawing(self, board_id: str, timeframe: str, drawing_id: str, patch: dict) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        tf_state = board.get_tf(timeframe)
        if not tf_state or drawing_id not in tf_state.drawings:
            return {"error": f"Drawing '{drawing_id}' not found"}
        tf_state.drawings[drawing_id] = {**tf_state.drawings[drawing_id], **patch, "id": drawing_id}
        return {"status": "ok", "drawing": tf_state.drawings[drawing_id]}

    def list_drawings(self, board_id: str, timeframe: str) -> list[dict]:
        board = self.boards.get(board_id)
        if not board:
            return []
        tf_state = board.get_tf(timeframe)
        return list(tf_state.drawings.values()) if tf_state else []

    # ========== 状态导出 ==========

    def get_full_state(self, board_id: str) -> dict:
        """获取画板完整状态（所有时间周期）"""
        board = self.boards.get(board_id)
        if not board:
            return {}
        return {
            "board_id": board_id,
            "name": board.name,
            "intervals": board.intervals,
            "current_timeframe": board.current_timeframe,
            "timeframes": {
                tf: self._tf_state_to_dict(board.timeframes[tf])
                for tf in board.timeframes
            }
        }

    def get_timeframe_state(self, board_id: str, timeframe: str) -> dict:
        """获取单个时间周期的状态"""
        board = self.boards.get(board_id)
        if not board:
            return {}
        tf_state = board.get_tf(timeframe)
        if not tf_state:
            return {}
        result = self._tf_state_to_dict(tf_state)
        result["board_id"] = board_id
        result["timeframe"] = timeframe
        return result

    def _tf_state_to_dict(self, tf_state: TimeframeState) -> dict:
        return {
            "interval": tf_state.interval,
            "ohlcv": tf_state.ohlcv,
            "markers": tf_state.markers,
            "indicators": {
                name: {k: v for k, v in ind.items() if k != "script_path"}
                for name, ind in tf_state.indicators.items()
            },
            "subplots": list(tf_state.subplots.values()),
            "drawings": list(tf_state.drawings.values()),
            "symbol": tf_state.symbol,
            "last_updated": tf_state.last_updated
        }
