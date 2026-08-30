"""
AgentKline - MCP 工具集
把 AgentKlineService 封装为 MCP 工具，供 AI agent 直接调用。
仅以 Streamable HTTP 形式挂载进 FastAPI（见 api/app.py 的 /mcp），
与 Web 共享同一 service 实例；不再作为独立 stdio 进程运行。
"""
import asyncio
import base64 as _b64
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

# service 由 api.app 绑定为与 Web 共享的同一实例
service = None

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "snapshots"
SNAPSHOT_DIR.mkdir(exist_ok=True)

mcp = FastMCP("agentkline")


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ============ 画板 ============
@mcp.tool()
def list_boards() -> str:
    """列出所有画板"""
    return _j(service.list_boards())

@mcp.tool()
def create_board(board_id: str, name: str = None, intervals: list = None) -> str:
    """创建画板。intervals 如 ["1d","4h"]"""
    return _j(service.create_board(board_id, name, intervals))

@mcp.tool()
def delete_board(board_id: str) -> str:
    """删除画板"""
    return _j(service.delete_board(board_id))

@mcp.tool()
def switch_board(board_id: str) -> str:
    """切换当前画板"""
    return _j(service.switch_board(board_id))


# ============ 时间周期 ============
@mcp.tool()
def list_timeframes(board_id: str) -> str:
    """列出画板的时间周期"""
    return _j(service.list_timeframes(board_id))

@mcp.tool()
def create_timeframe(board_id: str, interval: str) -> str:
    """给画板添加时间周期，如 1d/4h/1h"""
    return _j(service.create_timeframe(board_id, interval))

@mcp.tool()
def delete_timeframe(board_id: str, timeframe: str) -> str:
    """删除时间周期"""
    return _j(service.delete_timeframe(board_id, timeframe))


# ============ 数据 ============
@mcp.tool()
def set_datasource(board_id: str, timeframe: str, path: str, params: dict = None,
                   poll_interval: int = None, indicators: list = None) -> str:
    """配置数据源脚本（scripts/ 下的 .py）。poll_interval>0 则轮询实时刷新。
    indicators 可附带指标配置列表（随数据源一起加载）。"""
    return _j(service.set_datasource(board_id, timeframe, path, params, poll_interval, indicators))

@mcp.tool()
def load_history(board_id: str, timeframe: str, limit: int = 200) -> str:
    """向左加载更早的历史K线（前插）"""
    return _j(service.load_history(board_id, timeframe, limit))

@mcp.tool()
def run_script(board_id: str, timeframe: str, path: str, params: dict = None,
               save_as: str = None, indicator_name: str = None, subplot: str = None,
               scope: str = "board", display_name: str = None) -> str:
    """执行脚本。save_as: ohlcv/indicator/None。scope: board=所有周期(默认)/timeframe=仅本周期。
    save_as=indicator 且不传 indicator_name 时自动命名(前3参数+…)；display_name 可覆盖显示名。"""
    return _j(service.run_script(board_id, timeframe, path, params, save_as,
                                 indicator_name, subplot, scope, display_name))

@mcp.tool()
def get_state(board_id: str, timeframe: str) -> str:
    """获取画板+周期的完整状态（K线/指标/副图）"""
    return _j(service.get_state(board_id, timeframe))

@mcp.tool()
def get_current_view() -> str:
    """获取用户当前视图（画板/周期/可见时间窗口），由前端上报"""
    return _j(service.current_view or {})


# ============ 指标 ============
@mcp.tool()
def add_indicator(board_id: str, timeframe: str, name: str, values: list = None,
                  subplot: str = None, style: dict = None, type: str = None,
                  lines: list = None) -> str:
    """直接推送指标（静态值或多线 lines）"""
    return _j(service.add_indicator(board_id, timeframe, name, values, subplot, style, type, None, lines))

@mcp.tool()
def delete_indicator(board_id: str, timeframe: str, name: str) -> str:
    """删除指标"""
    return _j(service.delete_indicator(board_id, timeframe, name))

@mcp.tool()
def update_indicator(board_id: str, timeframe: str, name: str, params: dict = None,
                     style: dict = None, lines_style: dict = None,
                     display_name: str = None, auto_label: bool = None) -> str:
    """更新已推指标。params=新参数(触发重算)；style=整体样式；
    lines_style={线名:{color,lineWidth,lineStyle}}；display_name=覆盖显示名；
    auto_label=true 恢复自动命名。"""
    return _j(service.update_indicator(board_id, timeframe, name, params, style,
                                       lines_style, display_name, auto_label))

@mcp.tool()
def list_scripts() -> str:
    """列出可用的指标/数据源脚本"""
    return _j({"scripts": service.script_engine.list_scripts()})


# ============ 副图 ============
@mcp.tool()
def create_subplot(board_id: str, timeframe: str, name: str, height: int = 150, title: str = None) -> str:
    """创建副图"""
    return _j(service.create_subplot(board_id, timeframe, name, height, title))

@mcp.tool()
def delete_subplot(board_id: str, timeframe: str, name: str) -> str:
    """删除副图（连同其上指标）"""
    return _j(service.delete_subplot(board_id, timeframe, name))


# ============ 标记 ============
@mcp.tool()
def set_markers(board_id: str, timeframe: str, markers: list) -> str:
    """在K线主图设置标记（覆盖式）。time 为毫秒时间戳，需与K线bar时间对齐。
    字段: time/position(aboveBar|belowBar)/color/shape(arrowUp|arrowDown)/text"""
    return _j(service.set_markers(board_id, timeframe, markers))

@mcp.tool()
def add_drawing(board_id: str, timeframe: str, type: str, points: list,
                color: str = "#ef5350", line_width: int = 2, line_style: str = "solid",
                text: str = "") -> str:
    """画线。type: hline(水平,points=[{price}]) / trend(趋势,points=[{time,price},{time,price}])。
    time 为毫秒时间戳。"""
    drawing = {"type": type, "points": points, "color": color,
               "lineWidth": line_width, "lineStyle": line_style, "text": text}
    return _j(service.add_drawing(board_id, timeframe, drawing))

@mcp.tool()
def delete_drawing(board_id: str, timeframe: str, drawing_id: str) -> str:
    """删除划线"""
    return _j(service.delete_drawing(board_id, timeframe, drawing_id))

@mcp.tool()
def update_drawing(board_id: str, timeframe: str, drawing_id: str,
                   visible: bool = None, color: str = None, line_width: int = None,
                   line_style: str = None, text: str = None) -> str:
    """更新划线：visible(显隐)/color/line_width/line_style(solid|dashed|dotted)/text"""
    patch = {k: v for k, v in {"visible": visible, "color": color, "lineWidth": line_width,
                              "lineStyle": line_style, "text": text}.items() if v is not None}
    return _j(service.update_drawing(board_id, timeframe, drawing_id, patch))

@mcp.tool()
def list_drawings(board_id: str, timeframe: str) -> str:
    """列出画板+周期的所有划线"""
    return _j(service.list_drawings(board_id, timeframe))

@mcp.tool()
def get_data(board_id: str, timeframe: str, start: int = None, end: int = None) -> str:
    """获取区间K线+指标值+划线。不传start/end=用户当前view窗口。时间毫秒。"""
    return _j(service.get_data(board_id, timeframe, start, end))


# ============ 截图 ============
def _snapshot_content(board_id, timeframe):
    """返回 [文本(path), 图片(image)] 内容块。
    图片以标准 MCP ImageContent 返回，多模态客户端可直接"看见"；
    文本只带 path/size，避免把 base64 当纯文本塞进上下文烧 token。"""
    board = board_id or (service.state.current_board_id if service else None) or "board"
    path = SNAPSHOT_DIR / f"{board}_{timeframe or 'latest'}.png"
    if not path.exists():
        files = sorted(SNAPSHOT_DIR.glob("*.png"))
        if not files:
            return [TextContent(type="text",
                                text=_j({"error": "no snapshot",
                                         "hint": "需有浏览器连接 /ws 才能产生截图"}))]
        path = files[-1]
    meta = TextContent(type="text",
                       text=_j({"path": str(path), "size": path.stat().st_size}))
    img = ImageContent(type="image", data=_b64.b64encode(path.read_bytes()).decode(),
                       mimeType="image/png")
    return [meta, img]


@mcp.tool()
async def take_snapshot(board_id: str = None, timeframe: str = None, wait: float = 1.5):
    """触发前端截图并返回图片+路径。需有浏览器连着 /ws。
    发送 snapshot_request 后等待 wait 秒再读取最新快照。"""
    service.notify({"type": "snapshot_request", "board_id": board_id, "timeframe": timeframe})
    await asyncio.sleep(wait)
    return _snapshot_content(board_id, timeframe)


@mcp.tool()
def get_snapshot(board_id: str = None, timeframe: str = None):
    """读取最新快照（图片+路径）。快照由浏览器截图上传产生。"""
    return _snapshot_content(board_id, timeframe)



