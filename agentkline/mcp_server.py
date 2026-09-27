"""
AgentKline - MCP 工具集（v0.4.1 收口形态）
工具主体由 api/tools.py 的 REGISTRY 单一源生成（_j 字符串包装保持旧客户端解析契约）；
本模块仅保留两个手工工具：take_snapshot / get_snapshot（需 ImageContent 真图块，模型看图依赖）。
仅以 Streamable HTTP 形式挂载进 FastAPI（见 api/app.py 的 /mcp），与 Web 共享同一 service 实例。
"""
import asyncio
import base64 as _b64
import functools
import json

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

# service 由 api.app 绑定为与 Web 共享的同一实例
service = None

mcp = FastMCP("agentkline")


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _register_registry_tools():
    from .api.tools import REGISTRY
    for fn in REGISTRY:
        if not fn._api["mcp"]:
            continue

        @functools.wraps(fn)
        def wrapper(*args, _fn=fn, **kwargs):
            return _j(_fn(*args, **kwargs))

        mcp.tool(name=fn.__name__, description=(fn.__doc__ or "").strip())(wrapper)


_register_registry_tools()


@mcp.tool()
async def take_snapshot(board_id: str = None, timeframe: str = None, wait: float = 1.5,
                        allow_stale: bool = False):
    """触发前端截图并返回图片+路径。需有浏览器连着 /ws。
    发送 snapshot_request 后等待 wait 秒再读取最新快照。
    无浏览器在线时明确报 NO_BROWSER（不回退磁盘旧图，防僵尸快照误导）；
    allow_stale=true 显式接受最近磁盘快照（返回带 stale:true + stale_since 时间戳）。"""
    r = await service.take_snapshot(board_id, timeframe, wait, allow_stale)
    return _snapshot_content(r)


@mcp.tool()
def get_snapshot(board_id: str = None, timeframe: str = None):
    """读取最新快照（图片+路径）。快照由浏览器截图上传产生。"""
    return _snapshot_content(service.get_snapshot(board_id, timeframe))


def _snapshot_content(r):
    if not isinstance(r, dict) or r.get("error") or not r.get("image_b64"):
        return [TextContent(type="text", text=_j(r))]
    return [
        ImageContent(type="image", data=r["image_b64"], mimeType="image/png"),
        TextContent(type="text", text=_j({"path": r["path"], "size": r["size"],
                                          **({"stale": True, "stale_since": r.get("stale_since")}
                                             if r.get("stale") else {})})),
    ]
