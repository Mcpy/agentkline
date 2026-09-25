"""
共享层：service 单例、WS 广播、配置/鉴权 token、Pydantic 模型、通用助手。
web_app 与 agent_app 共用，保证两端口状态一致。
"""
import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import WebSocket, HTTPException, Request
from pydantic import BaseModel

from ..core.service import AgentKlineService

BASE_DIR = Path(__file__).resolve().parent.parent.parent
WEB_DIST = BASE_DIR / "web_dist"
SCRIPTS_DIR = BASE_DIR / "scripts"
SNAPSHOT_DIR = BASE_DIR / "snapshots"
SNAPSHOT_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("agentkline")

# 单一 service 实例，web/agent 两端口共享（CONFIG 加载后构造，见文件下方）
service = None


# ============ WebSocket 广播（共享连接表） ============
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws):
        await ws.accept()
        ws._ak_seq = 0  # 每连接自增 seq（排障用，无 ACK；恢复=重连重拉 init）
        self.active.append(ws)

    def disconnect(self, ws):
        if ws in self.active:
            self.active.remove(ws)

    def envelope(self, message: dict, ws=None) -> dict:
        """v0.4 标准信封硬切：{v, type, seq, ts, payload}；业务字段全进 payload"""
        import time as _t
        seq = 0
        if ws is not None:
            ws._ak_seq = getattr(ws, "_ak_seq", 0) + 1
            seq = ws._ak_seq
        return {"v": 1, "type": message.get("type"), "seq": seq,
                "ts": int(_t.time() * 1000),
                "payload": {k: v for k, v in message.items() if k != "type"}}

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(self.envelope(message, ws))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = ConnectionManager()


async def _notify(message: dict):
    await ws_manager.broadcast(message)


def _sync_notify(message: dict):
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_notify(message))
    except RuntimeError:
        pass


# ============ 配置 / 鉴权 token ============
def load_config() -> dict:
    cfg_path = BASE_DIR / "config.yaml"
    if not cfg_path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception as _e:
        logger.warning("config.yaml load failed: %s", _e)
        return {}


CONFIG = load_config()
service = AgentKlineService(str(SCRIPTS_DIR), (CONFIG.get("limits") or {}))
service.notify = _sync_notify
AUTH_TOKEN = (os.environ.get("AGENTKLINE_TOKEN")
              or (CONFIG.get("auth") or {}).get("token")
              or "").strip() or None


def check_agent_auth(request: Request) -> bool:
    """agent 端口全量鉴权：配置 token 则需 Bearer 匹配；否则仅本机。"""
    if AUTH_TOKEN:
        return request.headers.get("authorization") == f"Bearer {AUTH_TOKEN}"
    return bool(request.client) and request.client.host in ("127.0.0.1", "::1")


# ============ 登录预留点（web 端口） ============
async def current_web_user() -> dict:
    """预留登录扩展点：当前恒为匿名（无参，HTTP/WS 路由通用）。
    未来实现登录时，在此读取 cookie/session 校验并在未登录时 raise 401，
    即可让全部 web 路由受保护，无需改动各路由。"""
    return {"user": None, "auth": "anonymous"}


# ============ Pydantic Models ============
class BoardCreate(BaseModel):
    id: str
    name: Optional[str] = None
    intervals: Optional[list[str]] = None
    # v0.4 建板即锁：symbol+source 齐 = 锁定现场；皆无 = 空板（仅 agent 端口 /api/board/empty 或 MCP）
    symbol: Optional[str] = None
    source: Optional[str] = None
    params: Optional[dict] = None
    poll_s: Optional[int] = None

class TimeframeCreate(BaseModel):
    interval: str

class IndicatorPush(BaseModel):
    """v0.4 指标实例：inst_id 把手（不传自动生成）；script=计算型 / values|lines=冻结 blob"""
    inst_id: Optional[str] = None
    values: Optional[list] = None
    subplot: Optional[str] = None
    style: Optional[dict] = None
    markers: Optional[list[dict]] = None
    lines: Optional[list[dict]] = None
    script: Optional[str] = None
    params: Optional[dict] = None
    scope: Optional[str] = None
    display_name: Optional[str] = None

class SubplotCreate(BaseModel):
    name: str
    height: Optional[int] = 150
    title: Optional[str] = None

class SubplotUpdate(BaseModel):
    height: Optional[int] = None
    title: Optional[str] = None

class MarkersPush(BaseModel):
    markers: list[dict]

class ScriptRun(BaseModel):
    """v0.4 窄身：只执行返回，图上不留痕（save_as 废除）"""
    script: str
    params: Optional[dict] = None

class IndicatorUpdate(BaseModel):
    params: Optional[dict] = None
    style: Optional[dict] = None
    lines_style: Optional[dict] = None
    display_name: Optional[str] = None
    auto_label: Optional[bool] = None

class KlineSourceConfig(BaseModel):
    """槽配置（PUT 声明式幂等）：script 为 id；IDENTITY 键在 params 内须与板锁全等"""
    script: str
    params: Optional[dict] = None
    poll_s: Optional[int] = None

class SnapshotPush(BaseModel):
    image: str
    board_id: Optional[str] = None
    timeframe: Optional[str] = None


def _err(result):
    """错误码→HTTP 状态：SOURCE_LOCKED=409（带结构化 suggestion 一键改道）；其余 400"""
    if result.get("code") == "SOURCE_LOCKED":
        return HTTPException(status_code=409, detail=result)
    return HTTPException(status_code=400, detail=result["error"])


def _resolve(board_id, timeframe):
    board_id = board_id or service.state.current_board_id
    timeframe = timeframe or service.state.get_default_timeframe(board_id)
    return board_id, timeframe
