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
        # 物化缓存（v0.4 指标实例模型）：inst_id -> {values, lines, markers}
        self.ind_cache: dict[str, dict] = {}
        self.subplots: dict[str, dict] = {}    # name -> subplot config
        self.drawings: dict[str, dict] = {}    # id -> drawing (划线)
        self.symbol: str = ""
        self.last_updated: str = ""


_TF_UNIT = {"m": 0, "h": 1, "d": 2, "w": 3, "M": 4}


def tf_rank(iv: str):
    """周期排序键：时间短→长（15m < 1h < 4h < 1d < 1w < 1M）"""
    import re
    m = re.match(r"^(\d+)([mhdwM])$", iv or "")
    if not m:
        return (99, 0)
    return (_TF_UNIT.get(m.group(2), 99), int(m.group(1)))


class Board:
    """单个画板"""

    def __init__(self, board_id: str, name: str = None, intervals: list[str] = None):
        self.id = board_id
        self.name = name or board_id
        self.intervals = sorted(intervals or ["1d"], key=tf_rank)
        # 初始当前周期：1d 在列则用（交易面板惯例），否则最短档
        self.current_timeframe = ("1d" if "1d" in self.intervals
                                  else (self.intervals[0] if self.intervals else "1d"))
        self.timeframes: dict[str, TimeframeState] = {}
        for iv in self.intervals:
            self.timeframes[iv] = TimeframeState(iv)
        # 指标实例登记处（v0.4）：inst_id -> instance
        # instance = {inst_id, kind: recipe|blob, script, params, scope: board|timeframe,
        #             tf, target(副图名|None), style, lines_style, display_name,
        #             custom_label, auto_label, blob}
        self.ind_registry: dict[str, dict] = {}
        # 板锁（v0.4 一标的一板）：None=初始态(未锁定，仅 AI 可建)；
        # 锁定后 = {"script": id, "identity": {IDENTITY键: 值快照}}，不可变
        self.source_lock: Optional[dict] = None
        self.created_at = datetime.now().isoformat()

    @property
    def locked(self) -> bool:
        return self.source_lock is not None

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
        out = []
        for b in self.boards.values():
            lock = b.source_lock or {}
            ident = lock.get("identity") or {}
            out.append({
                "id": b.id, "name": b.name, "intervals": b.intervals,
                "current_timeframe": b.current_timeframe,
                "source_lock": b.source_lock,
                "locked": b.locked,
                # 显示链统一格式：源名: 标的名（去 kind/ 前缀；仅显示，非存储）
                "identity_display": (f"{str(lock.get('script', '')).split('/')[-1]}: {ident.get('symbol')}"
                                     if ident.get("symbol") and lock.get("script")
                                     else (ident.get("symbol") or lock.get("script") or b.id)),
            })
        return out

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
        board.intervals.sort(key=tf_rank)  # 短→长排序（优化点2）
        return {"status": "ok", "interval": interval, "intervals": board.intervals}

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

    MAX_BARS_PER_SLOT = 50000  # R8 上限护栏：越界截最旧 + dropped 回报（config 化留收口）

    def set_ohlcv(self, board_id: str, timeframe: str, ohlcv: list[dict],
                  markers: list[dict] = None) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        tf_state = board.ensure_tf(timeframe)
        dropped = 0
        if len(ohlcv) > self.MAX_BARS_PER_SLOT:
            dropped = len(ohlcv) - self.MAX_BARS_PER_SLOT
            ohlcv = ohlcv[-self.MAX_BARS_PER_SLOT:]
        tf_state.ohlcv = ohlcv
        if markers is not None:
            tf_state.markers = markers
        tf_state.last_updated = datetime.now().isoformat()
        out = {"status": "ok", "count": len(ohlcv)}
        if dropped:
            out["dropped"] = dropped
            out["drop_reason"] = f"max_bars_per_slot={self.MAX_BARS_PER_SLOT} 越界截最旧"
        return out

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

    # ========== 指标实例（v0.4：登记处 board 级 + 物化缓存 tf 级） ==========
    def add_instance(self, board_id: str, inst: dict) -> dict:
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        board.ind_registry[inst["inst_id"]] = inst
        return {"status": "ok", "inst_id": inst["inst_id"]}

    def get_instance(self, board_id: str, inst_id: str) -> Optional[dict]:
        board = self.boards.get(board_id)
        return board.ind_registry.get(inst_id) if board else None

    def list_instances(self, board_id: str) -> list[dict]:
        board = self.boards.get(board_id)
        return list(board.ind_registry.values()) if board else []

    def update_instance(self, board_id: str, inst_id: str, patch: dict) -> dict:
        board = self.boards.get(board_id)
        if not board or inst_id not in board.ind_registry:
            return {"error": f"Indicator '{inst_id}' not found"}
        board.ind_registry[inst_id].update(patch)
        return {"status": "ok"}

    def delete_instance(self, board_id: str, inst_id: str) -> dict:
        """登记处 + 各 tf 物化一次删净"""
        board = self.boards.get(board_id)
        if not board:
            return {"error": f"Board '{board_id}' not found"}
        existed = board.ind_registry.pop(inst_id, None) is not None
        for tf in board.timeframes.values():
            tf.ind_cache.pop(inst_id, None)
        if not existed:
            return {"error": f"Indicator '{inst_id}' not found"}
        return {"status": "ok"}

    def tf_instances(self, board_id: str, timeframe: str) -> list[dict]:
        """本周期生效实例：scope=board 或 (scope=timeframe 且 tf 匹配)"""
        board = self.boards.get(board_id)
        if not board:
            return []
        return [i for i in board.ind_registry.values()
                if i["scope"] == "board"
                or (i["scope"] == "timeframe" and i.get("tf") == timeframe)]

    def set_cache(self, board_id: str, timeframe: str, inst_id: str,
                  values: list = None, lines: list = None, markers: list = None) -> None:
        """物化缓存写入（NaN/Inf 清洗挂这里，覆盖所有入值路径）"""
        board = self.boards.get(board_id)
        if not board:
            return
        tf = board.ensure_tf(timeframe)
        tf.ind_cache[inst_id] = {"values": _clean(values), "lines": _clean(lines),
                                 "markers": _clean(markers)}

    def get_cache(self, board_id: str, timeframe: str, inst_id: str) -> Optional[dict]:
        board = self.boards.get(board_id)
        tf = board.get_tf(timeframe) if board else None
        return tf.ind_cache.get(inst_id) if tf else None

    def shift_blob_caches(self, board_id: str, timeframe: str, prepended: int) -> None:
        """backfill 前插后：blob 缓存头部补 None 保持索引对齐（recipe 随后全量重算不受影响）"""
        board = self.boards.get(board_id)
        tf = board.get_tf(timeframe) if board else None
        if not tf or prepended <= 0:
            return
        for inst_id, c in tf.ind_cache.items():
            inst = board.ind_registry.get(inst_id)
            if not inst or inst["kind"] != "blob":
                continue
            pad = [None] * prepended
            if c.get("values") is not None:
                c["values"] = pad + c["values"]
            for ln in (c.get("lines") or []):
                if ln.get("values") is not None:
                    ln["values"] = pad + ln["values"]

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
        # 同时删除 target 为该副图的所有指标实例（登记处+各tf缓存一次删净）
        for inst in [i for i in board.ind_registry.values() if i.get("target") == name]:
            self.delete_instance(board_id, inst["inst_id"])
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
                tf: self._tf_state_to_dict(board_id, board.timeframes[tf])
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
        result = self._tf_state_to_dict(board_id, tf_state)
        result["board_id"] = board_id
        result["timeframe"] = timeframe
        return result

    def _tf_state_to_dict(self, board_id: str, tf_state: TimeframeState) -> dict:
        # 指标 wire 格式：inst_id -> 物化缓存 + 实例元信息（前端/ init / switch 共用）
        indicators = {}
        for inst in self.tf_instances(board_id, tf_state.interval):
            c = tf_state.ind_cache.get(inst["inst_id"], {})
            indicators[inst["inst_id"]] = {
                **c,
                "inst_id": inst["inst_id"], "kind": inst["kind"],
                "script": inst["script"], "params": inst["params"],
                "scope": inst["scope"], "subplot": inst["target"],
                "style": inst["style"], "lines_style": inst["lines_style"],
                "display_name": inst.get("display_name") or inst.get("auto_label")
                                or inst["inst_id"],
            }
        return {
            "interval": tf_state.interval,
            "ohlcv": tf_state.ohlcv,
            "markers": tf_state.markers,
            "indicators": indicators,
            "subplots": list(tf_state.subplots.values()),
            "drawings": list(tf_state.drawings.values()),
            "symbol": tf_state.symbol,
            "last_updated": tf_state.last_updated
        }
