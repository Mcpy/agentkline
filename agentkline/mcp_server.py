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
    """创建画板。intervals 为初始周期列表（如 ["1d","4h"]），首个为默认周期。
    建板后用 set_datasource 或 run_script 灌K线。"""
    return _j(service.create_board(board_id, name, intervals))

@mcp.tool()
def delete_board(board_id: str) -> str:
    """删除画板（连同其所有周期、K线、指标、副图与画线，不可恢复）。"""
    return _j(service.delete_board(board_id))

@mcp.tool()
def switch_board(board_id: str) -> str:
    """切换当前画板，前端随之显示该画板（广播其默认周期状态）；用于 AI 主动展示。
    增删查工具仍需显式传 board_id。"""
    return _j(service.switch_board(board_id))


# ============ 时间周期 ============
@mcp.tool()
def list_timeframes(board_id: str) -> str:
    """列出画板的时间周期"""
    return _j(service.list_timeframes(board_id))

@mcp.tool()
def create_timeframe(board_id: str, interval: str) -> str:
    """给画板添加时间周期（如 1d/4h/1h）。新周期初始为空白，需另行 set_datasource 灌数据。"""
    return _j(service.create_timeframe(board_id, interval))

@mcp.tool()
def delete_timeframe(board_id: str, timeframe: str) -> str:
    """删除时间周期（连同其K线/指标/画线）。若删的是当前周期，自动回退到默认周期。"""
    return _j(service.delete_timeframe(board_id, timeframe))

@mcp.tool()
def switch_timeframe(board_id: str, timeframe: str) -> str:
    """切换当前时间周期，前端随之显示该周期（广播该周期状态）；用于 AI 主动展示，类比 switch_board。
    取数等工具仍需显式传 timeframe。"""
    return _j(service.switch_timeframe(board_id, timeframe))


# ============ 数据 ============
@mcp.tool()
def set_datasource(board_id: str, timeframe: str, path: str, params: dict = None,
                   poll_interval: int = None, indicators: list = None) -> str:
    """配置数据源脚本（scripts/ 下的 .py）。poll_interval>0 则轮询实时刷新。
    indicators 可附带指标配置列表（随数据源一起加载）。"""
    return _j(service.set_datasource(board_id, timeframe, path, params, poll_interval, indicators))

@mcp.tool()
def load_history(board_id: str, timeframe: str, limit: int = 200) -> str:
    """向左补充更早的历史K线（前插到现有最早一根之前）。
    场景：图表向左滚动、已加载的最早K线不够看时，回溯拉取更早行情（前端左滑也会自动触发）。
    前提：该画板/周期已配置数据源，且数据源脚本支持 until 参数（按时间回溯取数，如 ccxt_binance_btc）；
    数据源不支持 until（如 mock）时无数据可补，返回 prepended=0。
    返回：prepended(本次前插根数) / total(当前总根数)。"""
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
def overview(board_id: str, timeframe: str) -> str:
    """轻量结构总览：品种/周期/数据源/指标元信息/副图名/画线与标记计数等，
    不含K线与指标数值数组（省token）。探查'图上有什么'首选本工具；取数用 get_kline/get_indicators。"""
    return _j(service.get_overview(board_id, timeframe))

@mcp.tool()
def get_current_view() -> str:
    """获取用户当前视图（画板/周期/可见时间窗口），由前端上报"""
    return _j(service.current_view or {})

@mcp.tool()
def set_view_range(board_id: str, timeframe: str, from_time: int, to_time: int) -> str:
    """让前端聚焦到指定时间窗口（AI 主动把画面拉到某段时间，如回测亏损区间）。
    需先 switch_board/switch_timeframe 切到目标板/周期（前端只在当前显示的板/周期上应用）。
    from_time/to_time 为毫秒时间戳（误传秒自动×1000），需 from<to 且在已加载数据范围内。
    建议顺序：set_markers/add_drawing → switch_board → switch_timeframe → set_view_range。"""
    return _j(service.set_view_range(board_id, timeframe, from_time, to_time))


# ============ 指标 ============
@mcp.tool()
def add_indicator(board_id: str, timeframe: str, name: str, values: list = None,
                  subplot: str = None, style: dict = None, type: str = None,
                  lines: list = None, script: str = None, params: dict = None,
                  scope: str = "board", display_name: str = None) -> str:
    """加指标（统一入口）。
    - 计算型：给 script（如 'macd.py'）+params，服务端执行脚本算出值；例 add_indicator(name='MACD', script='macd.py')
    - 现成型：给 values 或多线 lines，直接落值
    - 两者皆无会报错。"""
    return _j(service.add_indicator(board_id, timeframe, name, values, subplot, style, type,
                                    None, lines, True, script=script, params=params,
                                    scope=scope, display_name=display_name))

@mcp.tool()
def delete_indicator(board_id: str, timeframe: str, name: str) -> str:
    """按名称删除指标（从图表移除；查看现有指标名可用 overview）。"""
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
    """列出 scripts/ 下可用脚本名，可作 run_script 的 path、add_indicator 的 script、
    set_datasource 的 path。"""
    return _j({"scripts": service.script_engine.list_scripts()})


# ============ 副图 ============
@mcp.tool()
def create_subplot(board_id: str, timeframe: str, name: str, height: int = 150, title: str = None) -> str:
    """创建副图——主图下方的独立小面板，用于放置指标（如 MACD/KDJ/成交量）。
    建好后用 add_indicator(subplot=名称) 把指标放进该副图；查看用 list_subplots。"""
    return _j(service.create_subplot(board_id, timeframe, name, height, title))

@mcp.tool()
def delete_subplot(board_id: str, timeframe: str, name: str) -> str:
    """删除副图（连同其上指标）"""
    return _j(service.delete_subplot(board_id, timeframe, name))


# ============ 标记 ============
@mcp.tool()
def set_markers(board_id: str, timeframe: str, markers: list) -> str:
    """在K线主图设置标记（覆盖式，替换该周期已有全部标记；读取用 get_markers）。
    单个标记字段：time(毫秒，需与某根K线bar时间对齐)/position(aboveBar|belowBar|inBar)/
    color/shape(circle|square|arrowUp|arrowDown)/text。"""
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
def list_subplots(board_id: str, timeframe: str) -> str:
    """列出画板+周期的所有副图"""
    return _j(service.list_subplots(board_id, timeframe))

@mcp.tool()
def get_kline(board_id: str, timeframe: str, start: int = None, end: int = None) -> str:
    """获取区间K线（含成交量）。不传start/end=用户当前view窗口。
    start/end 为毫秒时间戳 epoch_ms（如 1755000000000）；若误传秒（<1e11）会自动×1000。"""
    return _j(service.get_kline(board_id, timeframe, start, end))

@mcp.tool()
def get_indicators(board_id: str, timeframe: str, start: int = None, end: int = None,
                   names: str = None) -> str:
    """获取区间指标值，范围逻辑同 get_kline（不传=当前view）。
    names 逗号分隔可指定一个/多个指标（如 'MACD,sma_10'），不传=全部。"""
    name_list = [x.strip() for x in names.split(",") if x.strip()] if names else None
    return _j(service.get_indicators(board_id, timeframe, start, end, name_list))

@mcp.tool()
def get_markers(board_id: str, timeframe: str) -> str:
    """读取主图标记（买卖点等）。返回标记数组，字段同 set_markers（time/position/color/shape/text）；
    设置/覆盖用 set_markers。"""
    return _j(service.get_markers(board_id, timeframe))


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



