"""
agent 端口应用：面向 AI agent，全量强制鉴权（读+执行不区分）。
组合：只读 + 执行/管理 + /mcp。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .common import check_agent_auth, service, logger, AUTH_TOKEN
from . import routes


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # MCP 子应用 session manager 需在 agent 端口的事件循环内启动
    mcp_cm = None
    try:
        from .. import mcp_server
        mcp_cm = mcp_server.mcp.session_manager.run()
        await mcp_cm.__aenter__()
    except Exception as _e:
        logger.warning("MCP session manager not started: %s", _e)
    yield
    if mcp_cm:
        try:
            await mcp_cm.__aexit__(None, None, None)
        except Exception:
            pass


def create_agent_app() -> FastAPI:
    app = FastAPI(title="AgentKline Agent", version="0.4.2", lifespan=_lifespan)

    @app.middleware("http")
    async def require_token(request, call_next):
        if not check_agent_auth(request):
            code = 401 if AUTH_TOKEN else 403
            return JSONResponse(status_code=code,
                                content={"error": "unauthorized: agent API requires token (or localhost when unset)"})
        return await call_next(request)

    routes.register_tools(app, "agent")
    routes.register_snapshot(app)

    # MCP over Streamable HTTP，共享同一 service
    try:
        from .. import mcp_server
        mcp_server.service = service
        mcp_server.mcp.settings.streamable_http_path = "/"
        app.mount("/mcp", mcp_server.mcp.streamable_http_app())
        logger.info("MCP mounted at agent app /mcp")
    except Exception as _e:
        logger.warning("MCP mount skipped: %s", _e)

    logger.info("agent app ready (full auth)")
    return app
