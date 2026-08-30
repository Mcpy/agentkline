"""
路由分组注册。web_app 与 agent_app 按需挑选组合，避免重复代码。
- register_page / register_ws      : 页面 + WebSocket（仅 web）
- register_read                    : 只读（两端口都有）
- register_user_write              : 用户交互写（web 开放）
- register_exec                    : 执行/管理类（仅 agent，全量鉴权）
"""
from datetime import datetime
from typing import Optional

from fastapi import Query, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse

from .common import (service, ws_manager, WEB_DIST, SCRIPTS_DIR, SNAPSHOT_DIR,
                     _err, _resolve, logger,
                     BoardCreate, TimeframeCreate, OhlcvPush, IndicatorPush,
                     SubplotCreate, SubplotUpdate, MarkersPush, ScriptRun,
                     IndicatorUpdate, DataSourceConfig, LoadCsv, SnapshotPush)


# ============ 页面 / 静态 ============
def register_page(app):
    @app.get("/", response_class=HTMLResponse)
    async def index():
        web_index = WEB_DIST / "index.html"
        if web_index.exists():
            return web_index.read_text(encoding="utf-8")
        return HTMLResponse("<h1>frontend not built</h1><p>cd frontend && npm run build</p>",
                            status_code=503)


# ============ WebSocket ============
def register_ws(app):
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws_manager.connect(ws)
        try:
            board_id = service.state.current_board_id
            if board_id:
                tf = service.state.get_default_timeframe(board_id)
                await ws.send_json({"type": "init", "data": service.get_state(board_id, tf),
                                    "board_id": board_id, "timeframe": tf,
                                    "boards": service.state.list_boards()})
            else:
                await ws.send_json({"type": "init", "data": {}, "boards": []})
            while True:
                data = await ws.receive_text()
                if data == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)


# ============ 只读 ============
def register_read(app):
    @app.get("/api/boards")
    async def list_boards():
        return service.list_boards()

    @app.get("/api/board/{board_id}")
    async def switch_board(board_id: str):
        r = service.switch_board(board_id)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.get("/api/board/{board_id}/timeframes")
    async def list_timeframes(board_id: str):
        r = service.list_timeframes(board_id)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.get("/api/board/{board_id}/timeframe/{tf}")
    async def switch_timeframe(board_id: str, tf: str):
        r = service.switch_timeframe(board_id, tf)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.get("/api/state")
    async def get_state(board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        return service.get_state(board_id, timeframe)

    @app.get("/api/data")
    async def get_data(board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None),
                       start: Optional[int] = Query(None), end: Optional[int] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.get_data(board_id, timeframe, start, end)
        if r.get("error"): raise HTTPException(400, r["error"])
        return r

    @app.get("/api/subplots")
    async def list_subplots(board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        return service.list_subplots(board_id, timeframe)

    @app.get("/api/drawings")
    async def list_drawings(board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        return service.list_drawings(board_id, timeframe)

    @app.get("/api/config")
    async def get_config():
        return {"scripts_dir": str(SCRIPTS_DIR), "version": "0.2.0"}

    @app.get("/api/view")
    async def get_view():
        return service.current_view or {}

    @app.get("/api/snapshot")
    async def get_snapshot(board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board = board_id or service.state.current_board_id or "board"
        path = SNAPSHOT_DIR / f"{board}_{timeframe or 'latest'}.png"
        if not path.exists():
            files = sorted(SNAPSHOT_DIR.glob("*.png"))
            if not files:
                raise HTTPException(404, "no snapshot")
            path = files[-1]
        return FileResponse(path, media_type="image/png")


# ============ 用户交互写（web 开放） ============
def register_user_write(app):
    @app.post("/api/drawing")
    async def add_drawing(req: dict, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.add_drawing(board_id, timeframe, req)
        if r.get("error"): raise _err(r)
        return r

    @app.post("/api/drawing/{drawing_id}")
    async def update_drawing(drawing_id: str, req: dict, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.update_drawing(board_id, timeframe, drawing_id, req)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.delete("/api/drawing/{drawing_id}")
    async def delete_drawing(drawing_id: str, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.delete_drawing(board_id, timeframe, drawing_id)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.delete("/api/indicator/{name}")
    async def delete_indicator(name: str, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.delete_indicator(board_id, timeframe, name)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.post("/api/indicator/update/{name}")
    async def update_indicator(name: str, req: IndicatorUpdate, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.update_indicator(board_id, timeframe, name, req.params, req.style,
                                     req.lines_style, req.display_name, req.auto_label)
        if r.get("error"): raise HTTPException(500, r["error"])
        return r

    @app.delete("/api/board/{board_id}")
    async def delete_board(board_id: str):
        r = service.delete_board(board_id)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.delete("/api/board/{board_id}/timeframe/{tf}")
    async def delete_timeframe(board_id: str, tf: str):
        r = service.delete_timeframe(board_id, tf)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.post("/api/board/{board_id}/timeframe/{tf}/history")
    async def load_history(board_id: str, tf: str, req: dict = None):
        return service.load_history(board_id, tf, (req or {}).get("limit", 200))

    @app.post("/api/view")
    async def report_view(req: dict):
        service.current_view = {**req, "updated_at": datetime.now().isoformat()}
        return {"status": "ok"}

    @app.post("/api/snapshot")
    async def push_snapshot(req: SnapshotPush):
        return _save_snapshot(req)


def _save_snapshot(req: SnapshotPush):
    import base64 as b64
    data = req.image
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    raw = b64.b64decode(data)
    board = req.board_id or service.state.current_board_id or "board"
    tf = req.timeframe or "latest"
    path = SNAPSHOT_DIR / f"{board}_{tf}.png"
    path.write_bytes(raw)
    return {"status": "ok", "path": str(path), "size": len(raw)}


# ============ 执行/管理（agent 全量鉴权） ============
def register_exec(app):
    @app.post("/api/run-script")
    async def run_script(req: ScriptRun, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.run_script(board_id, timeframe, req.path, req.params, req.save_as,
                               req.indicator_name, req.subplot, req.scope or "board",
                               req.display_name)
        if r.get("error"): raise HTTPException(500, r["error"])
        return r

    @app.post("/api/ohlcv")
    async def push_ohlcv(req: OhlcvPush, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        if not board_id: raise HTTPException(400, "No board")
        r = service.set_ohlcv(board_id, timeframe, req.ohlcv, req.markers)
        if r.get("error"): raise _err(r)
        return r

    @app.post("/api/markers")
    async def push_markers(req: MarkersPush, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.set_markers(board_id, timeframe, req.markers)
        if r.get("error"): raise _err(r)
        return r

    @app.post("/api/load-csv")
    async def load_csv(req: LoadCsv, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.load_csv(board_id, timeframe, req.path, req.time_col)
        if r.get("error"): raise _err(r)
        return r

    @app.post("/api/indicator")
    async def push_indicator(req: IndicatorPush, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.add_indicator(board_id, timeframe, req.name, req.values, req.subplot,
                                  req.style, req.type, req.markers, req.lines, req.replace)
        if r.get("error"): raise HTTPException(400, r["error"])
        return r

    @app.post("/api/indicator/refresh/{name}")
    async def refresh_indicator(name: str, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.refresh_indicator(board_id, timeframe, name)
        if r.get("error"): raise HTTPException(400, r["error"])
        return r

    @app.post("/api/board")
    async def create_board(req: BoardCreate):
        r = service.create_board(req.id, req.name, req.intervals)
        if r.get("error"): raise _err(r)
        return r

    @app.put("/api/board/{board_id}")
    async def update_board(board_id: str, req: dict):
        r = service.update_board(board_id, req)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.post("/api/board/{board_id}/timeframe")
    async def create_timeframe(board_id: str, req: TimeframeCreate):
        r = service.create_timeframe(board_id, req.interval)
        if r.get("error"): raise _err(r)
        return r

    @app.post("/api/board/{board_id}/timeframe/{tf}/datasource")
    async def set_datasource(board_id: str, tf: str, req: DataSourceConfig):
        r = service.set_datasource(board_id, tf, req.path, req.params, req.poll_interval, req.indicators)
        if r.get("error"): raise HTTPException(500, r["error"])
        return r

    @app.get("/api/board/{board_id}/timeframe/{tf}/datasource")
    async def get_datasource(board_id: str, tf: str):
        return service.get_datasource(board_id, tf)

    @app.delete("/api/board/{board_id}/timeframe/{tf}/datasource")
    async def delete_datasource(board_id: str, tf: str):
        return service.delete_datasource(board_id, tf)

    @app.post("/api/board/{board_id}/timeframe/{tf}/refresh")
    async def refresh_timeframe(board_id: str, tf: str):
        return service.refresh_timeframe(board_id, tf)

    @app.post("/api/board/{board_id}/timeframe/{tf}/history")
    async def load_history(board_id: str, tf: str, req: dict = None):
        return service.load_history(board_id, tf, (req or {}).get("limit", 200))

    @app.post("/api/subplot")
    async def create_subplot(req: SubplotCreate, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.create_subplot(board_id, timeframe, req.name, req.height, req.title)
        if r.get("error"): raise _err(r)
        return r

    @app.put("/api/subplot/{name}")
    async def update_subplot(name: str, req: SubplotUpdate, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.update_subplot(board_id, timeframe, name, req.height, req.title)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.delete("/api/subplot/{name}")
    async def delete_subplot(name: str, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.delete_subplot(board_id, timeframe, name)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    # agent 也可经 REST 画线（鉴权）
    @app.post("/api/drawing")
    async def add_drawing(req: dict, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.add_drawing(board_id, timeframe, req)
        if r.get("error"): raise _err(r)
        return r

    @app.post("/api/drawing/{drawing_id}")
    async def update_drawing(drawing_id: str, req: dict, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.update_drawing(board_id, timeframe, drawing_id, req)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.delete("/api/drawing/{drawing_id}")
    async def delete_drawing(drawing_id: str, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.delete_drawing(board_id, timeframe, drawing_id)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r
