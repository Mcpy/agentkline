"""
路由分组注册。web_app 与 agent_app 按需挑选组合，避免重复代码。
- register_page / register_ws      : 页面 + WebSocket（仅 web）
- register_read                    : 只读（两端口都有）
- register_user_write              : 用户交互写（web 开放）
- register_manage                  : 管理删改：删板/删周期/删改指标（两端口都有）
- register_exec                    : 执行/管理类（仅 agent，全量鉴权）
"""
from datetime import datetime
from typing import Optional

from fastapi import Query, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse

from ..core import skills as _skills
from .common import (service, ws_manager, WEB_DIST, SCRIPTS_DIR, SNAPSHOT_DIR,
                     _err, _resolve, logger,
                     BoardCreate, TimeframeCreate, IndicatorPush,
                     SubplotCreate, SubplotUpdate, MarkersPush, ScriptRun,
                     IndicatorUpdate, KlineSourceConfig, SnapshotPush)


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


# ============ 只读 ============
def register_read(app):
    @app.get("/api/boards")
    async def list_boards():
        return service.list_boards()

    @app.get("/api/skills")
    async def list_skills():
        """skills 目录列表（与 MCP list_skills 对齐的 REST 薄镜像）"""
        return {"skills": _skills.list_skills()}

    @app.get("/api/skills/{name}")
    async def load_skill(name: str):
        """skill 全文（与 MCP load_skill 对齐）"""
        r = _skills.load_skill(name)
        if r.get("error"):
            raise HTTPException(404, r["error"])
        return r

    @app.get("/api/board/{board_id}/interval_options")
    async def interval_options(board_id: str):
        """周期"+"按钮数据：{online, supported, current, addable}；仅实时源 online=True"""
        r = service.interval_options(board_id)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.get("/api/search")
    async def search_symbols(q: str = "", refresh: bool = False):
        """标的搜索（P1 搜索流，web+agent）：行=完整二元组(源,裸符号)+●现场徽标；索引 TTL 日级"""
        return service.search_symbols(q, refresh)

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

    @app.get("/api/kline")
    async def get_kline(board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None),
                        start: Optional[int] = Query(None), end: Optional[int] = Query(None)):
        """纯 K 线（含成交量）区间切片；不传范围=当前 view"""
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.get_kline(board_id, timeframe, start, end)
        if r.get("error"): raise HTTPException(400, r["error"])
        return r

    @app.get("/api/indicators")
    async def get_indicators(board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None),
                             start: Optional[int] = Query(None), end: Optional[int] = Query(None),
                             instances: Optional[str] = Query(None)):
        """指标值区间切片；instances 逗号分隔按 inst_id 过滤，默认全部"""
        board_id, timeframe = _resolve(board_id, timeframe)
        inst_list = [x.strip() for x in instances.split(",") if x.strip()] if instances else None
        r = service.get_indicators(board_id, timeframe, start, end, inst_list)
        if r.get("error"): raise HTTPException(400, r["error"])
        return r

    @app.get("/api/markers")
    async def get_markers(board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.get_markers(board_id, timeframe)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.get("/api/overview")
    async def get_overview(board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        """轻量结构总览（不含 K 线/指标数值数组）"""
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.get_overview(board_id, timeframe)
        if r.get("error"): raise HTTPException(404, r["error"])
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
        return {"scripts_dir": str(SCRIPTS_DIR), "version": "0.4.0"}

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
    @app.post("/api/board")
    async def create_board(req: BoardCreate):
        """建板即锁（用户搜索流/带 symbol 的 agent）。裸板=agent 端口 /api/board/empty 或 MCP 不传 symbol"""
        if not req.symbol or not req.source:
            raise HTTPException(400, "LOCK_REQUIRES_SOURCE: POST /api/board 需 symbol+source"
                                  "（裸板请走 agent 端口 /api/board/empty 或 MCP create_board）")
        r = service.create_board(req.id, req.name, req.intervals, req.symbol,
                                 req.source, req.params, req.poll_s)
        if r.get("error"): raise _err(r)
        return r

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

    @app.post("/api/board/{board_id}/timeframe/{tf}/backfill")
    async def backfill(board_id: str, tf: str, req: dict = None):
        """向左补更早历史（原 /history 硬切改名）；CAPS.backfill 门控"""
        return service.backfill(board_id, tf, (req or {}).get("limit", 200))

    @app.post("/api/view")
    async def report_view(req: dict):
        service.current_view = {**req, "updated_at": datetime.now().isoformat()}
        return {"status": "ok"}

    @app.post("/api/snapshot")
    async def push_snapshot(req: SnapshotPush):
        return _save_snapshot(req)


# ============ 管理（删板/删周期/删改指标；web 与 agent 均挂载） ============

    @app.post("/api/markers")
    async def push_markers(req: MarkersPush, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.set_markers(board_id, timeframe, req.markers)
        if r.get("error"): raise _err(r)
        return r

    @app.post("/api/board/{board_id}/timeframe")
    async def create_timeframe(board_id: str, req: TimeframeCreate):
        """加周期（web 发起权）：在线板自动注入 {script, identity+interval}；服务端排序+INTERVALS 校验"""
        r = service.create_timeframe(board_id, req.interval)
        if r.get("error"): raise _err(r)
        return r


def register_manage(app):
    @app.delete("/api/indicator/{inst_id}")
    async def delete_indicator(inst_id: str, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.delete_indicator(board_id, timeframe, inst_id)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.put("/api/indicator/{inst_id}")
    async def update_indicator(inst_id: str, req: IndicatorUpdate, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        """统一更新（杂交路径清理：原 POST /api/indicator/update/{name} 改 PUT 声明式）"""
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.update_indicator(board_id, timeframe, inst_id, req.params, req.style,
                                     req.lines_style, req.display_name, req.auto_label)
        if r.get("error"): raise _err(r)
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
    @app.get("/api/scripts")
    async def list_scripts():
        """列出全部脚本（双根；与 MCP list_scripts 对齐）：[{id,kind,source,display,desc,params,caps,identity}]"""
        return {"scripts": service.script_engine.list_scripts()}

    @app.post("/api/board/empty")
    async def create_empty_board(req: BoardCreate):
        """裸板（未锁定初始态）：仅 agent 端口。用户侧无空板（建板即锁/删光落引导页）"""
        r = service.create_board(req.id, req.name, req.intervals)
        if r.get("error"): raise _err(r)
        return r

    @app.post("/api/scripts")
    async def save_script(req: dict):
        """保存自定义脚本到 custom 根（保存即校验）。body: {id: 'kind/name', code: '...'}"""
        sid, code = req.get("id"), req.get("code")
        if not sid or not code:
            raise HTTPException(400, "SAVE_EMPTY: 需要 id 与 code")
        r = service.save_script(sid, code)
        if r.get("error"):
            raise HTTPException(400, r["error"])
        return r

    @app.post("/api/view/range")
    async def set_view_range(req: dict, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        """让前端聚焦到指定时间窗口 {from, to}（毫秒；AI 主动展示某段时间）"""
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.set_view_range(board_id, timeframe, req.get("from"), req.get("to"))
        if r.get("error"): raise HTTPException(400, r["error"])
        return r

    @app.post("/api/run-script")
    async def run_script(req: ScriptRun):
        """执行脚本（窄身）：只返回结果，图上不留痕。script 为 id（kind/name）"""
        r = service.run_script(req.script, req.params)
        if r.get("error"): raise HTTPException(500, r["error"])
        return r

    @app.post("/api/indicator")
    async def push_indicator(req: IndicatorPush, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.add_indicator(board_id, timeframe, inst_id=req.inst_id, values=req.values,
                                  subplot=req.subplot, style=req.style, markers=req.markers,
                                  lines=req.lines, script=req.script, params=req.params,
                                  scope=req.scope, display_name=req.display_name)
        if r.get("error"): raise HTTPException(400, r["error"])
        return r

    @app.post("/api/indicator/refresh/{inst_id}")
    async def refresh_indicator(inst_id: str, board_id: Optional[str] = Query(None), timeframe: Optional[str] = Query(None)):
        board_id, timeframe = _resolve(board_id, timeframe)
        r = service.refresh_indicator(board_id, timeframe, inst_id)
        if r.get("error"): raise _err(r)
        return r

    @app.put("/api/board/{board_id}")
    async def update_board(board_id: str, req: dict):
        r = service.update_board(board_id, req)
        if r.get("error"): raise HTTPException(404, r["error"])
        return r

    @app.put("/api/board/{board_id}/timeframe/{tf}/kline_source")
    async def set_kline_source(board_id: str, tf: str, req: KlineSourceConfig):
        """声明式幂等配置 K 线来源；撞锁=409 SOURCE_LOCKED（detail 带 suggestion 一键改道）"""
        r = service.set_kline_source(board_id, tf, req.script, req.params, req.poll_s)
        if r.get("error"): raise _err(r)
        return r

    @app.get("/api/board/{board_id}/timeframe/{tf}/kline_source")
    async def get_kline_source(board_id: str, tf: str):
        return service.get_kline_source(board_id, tf)

    @app.post("/api/board/{board_id}/timeframe/{tf}/refresh")
    async def refresh_timeframe(board_id: str, tf: str):
        return service.refresh_timeframe(board_id, tf)

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
