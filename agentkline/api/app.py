"""
AgentKline 装配入口。
一个进程、共享 service，起两个端口：
  - web   端口（默认 0.0.0.0:8765）：用户浏览器，无鉴权（登录预留）
  - agent 端口（默认 127.0.0.1:8766）：AI agent，全量强制鉴权 + /mcp
端口/地址可在 config.yaml 的 server.web / server.agent 配置，或被环境变量覆盖。
"""
import os
import asyncio
import logging

from .common import CONFIG, service, logger, set_main_loop
from .web_app import create_web_app
from .agent_app import create_agent_app

web_app = create_web_app()
agent_app = create_agent_app()

# 兼容：单 app 场景（如仅 uvicorn agentkline.api.app:app）指向 web
app = web_app


def _server_cfg():
    srv = CONFIG.get("server") or {}
    web = srv.get("web") or {}
    agent = srv.get("agent") or {}
    return {
        "web_host": os.environ.get("AGENTKLINE_WEB_HOST") or web.get("host") or "0.0.0.0",
        "web_port": int(os.environ.get("AGENTKLINE_WEB_PORT") or web.get("port") or 8765),
        "agent_host": os.environ.get("AGENTKLINE_AGENT_HOST") or agent.get("host") or "127.0.0.1",
        "agent_port": int(os.environ.get("AGENTKLINE_AGENT_PORT") or agent.get("port") or 8766),
    }


async def _serve():
    import uvicorn
    cfg = _server_cfg()
    logger.info("web   listen %s:%s", cfg["web_host"], cfg["web_port"])
    logger.info("agent listen %s:%s", cfg["agent_host"], cfg["agent_port"])

    set_main_loop(asyncio.get_running_loop())
    service.datasource.start_polling()
    s_web = uvicorn.Server(uvicorn.Config(web_app, host=cfg["web_host"], port=cfg["web_port"],
                                          log_level="warning"))
    s_agent = uvicorn.Server(uvicorn.Config(agent_app, host=cfg["agent_host"], port=cfg["agent_port"],
                                            log_level="warning"))
    try:
        await asyncio.gather(s_web.serve(), s_agent.serve())
    finally:
        service.datasource.stop_all()
        service.watchlist.stop()
        logger.info("AgentKline stopped.")


def main_entry():
    """pip 入口：agentkline"""
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main_entry()
