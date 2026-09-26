"""
路由注册（v0.4.1 生成器形态）：REST 端点由 api/tools.py 的 REGISTRY 单一源生成，
手工薄镜像退役。本模块只保留三类手工出口（豁免清单）：
  1. 页面 / 静态（/）
  2. WebSocket（/ws）
  3. 快照二进制（GET /api/snapshot FileResponse；POST /api/snapshot base64 上传）
绑定约定见 tools.py 模块 docstring：POST/PUT=flat body；GET/DELETE=path+query。
组→端口：read/user_write/manage=[web,agent]；exec=[agent]（web 写端点=登录挂载面承诺不变）。
"""
import base64 as b64
from typing import Optional

from fastapi import Request, Response, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse

from .common import (service, ws_manager, WEB_DIST, SNAPSHOT_DIR, _resolve, logger)
from .tools import REGISTRY, ports_for

_CAST = {"int": int, "float": float, "bool": lambda v: str(v).lower() in ("1", "true", "yes"),
         "str": str}


def _cast(annotation, raw):
    name = getattr(annotation, "__name__", None) or str(annotation)
    fn = _CAST.get(name)
    if fn is None or raw is None:
        return raw
    try:
        return fn(raw)
    except (TypeError, ValueError):
        return raw


def _make_endpoint(fn, meta):
    import inspect
    sig = inspect.signature(fn)
    path_params = [p for p in meta["params"] if "{" + p + "}" in meta["path"]]
    is_body = meta["method"] in ("POST", "PUT")

    async def endpoint(request: Request, response: Response):
        # API GET 禁启发式缓存（否则前端同 URL 复取命中旧响应，如 search 的 watched 标志）
        if meta["method"] == "GET":
            response.headers["Cache-Control"] = "no-store"
        kwargs = {}
        for p in path_params:
            kwargs[p] = request.path_params.get(p)
        if is_body:
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                raise HTTPException(400, "BODY_NOT_OBJECT: POST/PUT 需 JSON 对象")
            if meta.get("rest_guard") == "lock" and (not body.get("symbol") or not body.get("source")):
                raise HTTPException(400, "LOCK_REQUIRES_SOURCE: POST /api/board 需 symbol+source"
                                  "（裸板请走 agent 端口 /api/board/empty 或 MCP create_board）")
            for name, param in sig.parameters.items():
                if name in path_params:
                    continue
                key = meta["aliases"].get(name, name)
                if key in body:
                    kwargs[name] = body[key]
        else:
            for name, param in sig.parameters.items():
                if name in path_params:
                    continue
                raw = request.query_params.get(name)
                if raw is not None:
                    kwargs[name] = _cast(param.annotation, raw)
        result = fn(**kwargs)
        if hasattr(result, "__await__"):
            result = await result
        if isinstance(result, dict) and result.get("error") and not meta.get("err_passthrough"):
            if result.get("code") == "SOURCE_LOCKED":
                raise HTTPException(409, result)
            raise HTTPException(meta["err_status"], result["error"])
        return result

    endpoint.__name__ = fn.__name__
    endpoint.__doc__ = fn.__doc__
    return endpoint


def register_tools(app, port):
    for fn in REGISTRY:
        meta = fn._api
        if not meta["rest"] or port not in ports_for(meta["group"]):
            continue
        app.add_api_route(meta["path"], _make_endpoint(fn, meta),
                          methods=[meta["method"]], name=fn.__name__)


# ============ 豁免：页面 ============
def register_page(app):
    @app.get("/", response_class=HTMLResponse)
    async def index():
        web_index = WEB_DIST / "index.html"
        if web_index.exists():
            # no-store：前端发版后浏览器必须拿新 index（资产名带 hash 可长缓存，index 不行）
            return HTMLResponse(web_index.read_text(encoding="utf-8"),
                                headers={"Cache-Control": "no-store"})
        return HTMLResponse("<h1>frontend not built</h1><p>cd frontend && npm run build</p>",
                            status_code=503)


# ============ 豁免：WebSocket ============
def register_ws(app):
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws_manager.connect(ws)
        try:
            board_id = service.state.current_board_id
            if board_id:
                tf = service.state.get_default_timeframe(board_id)
                await ws.send_json(ws_manager.envelope(
                    {"type": "init", "data": service.get_state_windowed(board_id, tf),
                     "board_id": board_id, "timeframe": tf,
                     "boards": service.state.list_boards()}, ws))
            else:
                await ws.send_json(ws_manager.envelope(
                    {"type": "init", "data": {}, "boards": []}, ws))
            while True:
                data = await ws.receive_text()
                if data == "ping":
                    await ws.send_json(ws_manager.envelope({"type": "pong"}, ws))
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)


# ============ 豁免：快照二进制 ============
def register_snapshot(app):
    @app.get("/api/snapshot")
    async def get_snapshot_file(board_id: Optional[str] = None, timeframe: Optional[str] = None):
        board = board_id or service.state.current_board_id or "board"
        path = SNAPSHOT_DIR / f"{board}_{timeframe or 'latest'}.png"
        if not path.exists():
            files = sorted(SNAPSHOT_DIR.glob("*.png"))
            if not files:
                raise HTTPException(404, "no snapshot")
            path = files[-1]
        return FileResponse(path, media_type="image/png")

    @app.post("/api/snapshot")
    async def push_snapshot(req: dict):
        data = req.get("image", "")
        if data.startswith("data:"):
            data = data.split(",", 1)[1]
        raw = b64.b64decode(data)
        board = req.get("board_id") or service.state.current_board_id or "board"
        tf = req.get("timeframe") or "latest"
        path = SNAPSHOT_DIR / f"{board}_{tf}.png"
        path.write_bytes(raw)
        return {"status": "ok", "path": str(path), "size": len(raw)}
