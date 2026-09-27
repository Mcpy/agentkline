"""
web 端口应用：面向用户浏览器，无鉴权（登录预留 current_web_user）。
组合：页面 + WS + 只读 + 用户交互写。
"""
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles

from .common import WEB_DIST, current_web_user, logger
from . import routes


def create_web_app() -> FastAPI:
    # 依赖级登录预留点：未来把 current_web_user 换成真实校验即可全量生效
    app = FastAPI(title="AgentKline Web", version="0.4.3",
                  dependencies=[Depends(current_web_user)])
    if (WEB_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(WEB_DIST / "assets")), name="assets")

    routes.register_page(app)
    routes.register_ws(app)
    routes.register_tools(app, "web")
    routes.register_snapshot(app)
    logger.info("web app ready (open, login hook=%s)", current_web_user.__name__)
    return app
