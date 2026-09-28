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


def _warm_network_stack():
    """v0.4.3 bug5 续：主线程预热 requests/urllib3/DNS/SSL——
    轮询 loop 的首次 fetch 在 executor 子线程冷启动曾观测到永久挂起
    （主线程同调用 0s 健康），预热把首次导入与解析移出子线程路径。"""
    try:
        import requests
        requests.get("https://fapi.binance.com/fapi/v1/ping", timeout=5)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("network warm-up 失败（不阻塞启动）: %s", e)


async def _serve():
    import uvicorn
    cfg = _server_cfg()
    logger.info("web   listen %s:%s", cfg["web_host"], cfg["web_port"])
    logger.info("agent listen %s:%s", cfg["agent_host"], cfg["agent_port"])

    _warm_network_stack()
    from .common import SCRIPTS_DIR
    logger.info("custom scripts root: %s", SCRIPTS_DIR)
    if "site-packages" in str(SCRIPTS_DIR):
        logger.warning("custom 根位于 site-packages 内：venv 重建会丢失自建脚本！"
                       "建议设 AGENTKLINE_SCRIPTS_DIR 指向用户目录（如 ~/.agentkline/scripts）")
    set_main_loop(asyncio.get_running_loop())
    # v0.4.4 启动预热：后台建搜索索引（不阻塞启动；更新机制不变=TTL 日级懒更新+手动 refresh+新源懒建）
    import threading as _th
    _th.Thread(target=service.warmup_symbol_index, daemon=True, name="index-warmup").start()
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
