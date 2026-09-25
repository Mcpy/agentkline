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

from .core import skills as _skills

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
def create_board(board_id: str, name: str = None, intervals: list = None,
                 symbol: str = None, source: str = None, params: dict = None,
                 poll_s: int = None) -> str:
    """创建画板。intervals 为初始周期列表（如 ["1d","4h"]），首个为默认周期。
    给 symbol+source = 建板即锁（一标的一板：source_lock={script, identity 快照}），并自动配置默认周期；
    皆无 = 裸板（未锁定初始态，仅 AI 可建），首配 set_kline_source 时锁定。
    换标的/换源被锁禁掉 → 请新建画板（撞锁返回 SOURCE_LOCKED+suggestion）。"""
    return _j(service.create_board(board_id, name, intervals, symbol, source, params, poll_s))

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
    """给画板添加时间周期（如 1d/4h/1h）。已锁定在线板：新周期槽由系统自动注入
    {script, identity+interval} 直接出图；离线/裸板新槽为空白待配。"""
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
def set_kline_source(board_id: str, timeframe: str, script: str, params: dict = None,
                     poll_s: int = None) -> str:
    """声明式配置 K 线来源（幂等，PUT 语义）。script 为 id（kind/name，如 datasource/ccxt_binance）。
    空板首配=锁定；已锁板须 script 与 IDENTITY 键全等，违则 SOURCE_LOCKED（带 suggestion 一键改道建板）。
    IDENTITY 之外 params=操作参数自由改（改即重拉）；仅 poll_s 变=不碰数据；poll_s>0 轮询实时刷新。
    附指标请用 add_indicator（打包参已废除）。"""
    return _j(service.set_kline_source(board_id, timeframe, script, params, poll_s))

@mcp.tool()
def backfill(board_id: str, timeframe: str, limit: int = 200) -> str:
    """向左补充更早的历史K线（前插到现有最早一根之前）。
    场景：图表向左滚动、已加载的最早K线不够看时，回溯拉取更早行情（前端左滑也会自动触发）。
    前提：该画板/周期已配置数据源，且其 CAPS.backfill=True（如 datasource/ccxt_binance、datasource/mock_btc）；
    无 backfill 徽章（如 datasource/csv）返回 prepended=0 并注明 NO_BACKFILL。
    返回：prepended(本次前插根数) / total(当前总根数)。"""
    return _j(service.backfill(board_id, timeframe, limit))

@mcp.tool()
def run_script(script: str, params: dict = None) -> str:
    """执行脚本并返回结果（窄身：图上不留痕，save_as 已废除）。
    script 为 id（kind/name，如 indicator/macd、datasource/mock_btc）；裸文件名已废弃。
    指标上图 = save_script + add_indicator(script=...)；K线入图 = set_kline_source 配方。"""
    return _j(service.run_script(script, params))

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
def add_indicator(board_id: str, timeframe: str, inst_id: str = None, values: list = None,
                  subplot: str = None, style: dict = None,
                  lines: list = None, script: str = None, params: dict = None,
                  scope: str = None, display_name: str = None) -> str:
    """加指标（统一入口，inst_id 把手）。
    - 计算型 recipe：给 script（id 格式 kind/name，如 'indicator/macd'）+params，随K线自动重算
    - 冻结 blob：给 values 或多线 lines，钉死本周期（传 scope 报 BLOB_SCOPE）
    - inst_id 撞名报 INST_EXISTS；不传自动 macd_2 式生成；两者皆无报 EMPTY_INDICATOR。"""
    return _j(service.add_indicator(board_id, timeframe, inst_id=inst_id, values=values,
                                    subplot=subplot, style=style, lines=lines,
                                    script=script, params=params,
                                    scope=scope, display_name=display_name))

@mcp.tool()
def delete_indicator(board_id: str, timeframe: str, inst_id: str) -> str:
    """按 inst_id 删除指标实例（登记处+各周期物化一次删净；现有 inst_id 见 overview）。"""
    return _j(service.delete_indicator(board_id, timeframe, inst_id))

@mcp.tool()
def update_indicator(board_id: str, timeframe: str, inst_id: str, params: dict = None,
                     style: dict = None, lines_style: dict = None,
                     display_name: str = None, auto_label: bool = None) -> str:
    """更新指标实例（inst_id 把手）。params=新参数(重声明配方触发重算)；style=整体样式；
    lines_style={线名:{color,lineWidth,lineStyle}}；display_name=覆盖显示名；
    auto_label=true 恢复自动命名。blob 改 params 报错。"""
    return _j(service.update_indicator(board_id, timeframe, inst_id, params, style,
                                       lines_style, display_name, auto_label))

@mcp.tool()
def list_scripts() -> str:
    """列出全部脚本（双根：builtin 内置只读 / custom 可写）。
    返回 [{id, kind, source, display, desc, params, caps, identity}]：
    id=kind/name 是一切引用的唯一格式；caps=能力徽章（backfill/symbols/ticker）；
    identity=板锁身份键（如 ["symbol"]）。写新脚本前先读 load_skill('script-authoring')。"""
    return _j({"scripts": service.script_engine.list_scripts()})


@mcp.tool()
def search_symbols(q: str = "", refresh: bool = False) -> str:
    """标的搜索（P1）：返回 rows=[{symbol, source, display, has_board}]，行=完整二元组(源,裸符号)；
    has_board=True=该二元组已有现场(●徽标，防重复建板)。索引=CAPS.symbols 源首用全量+TTL 日级，
    搜索永不穿透交易所；refresh=true 强刷索引。无徽章源用 @源名 裸符号 直配。"""
    return _j(service.search_symbols(q, refresh))


@mcp.tool()
def save_script(id: str, code: str) -> str:
    """保存自定义脚本到 custom 根（保存即校验：main 存在/CAPS 一致性/字面元数据合法）。
    id=kind/name（kind∈datasource/indicator/strategy）；内置脚本不可改。
    契约：datasource main(params[, until])→bars；indicator main(params, ohlcv)→values|{values,lines,markers}；
    元数据 NAME/DESC/PARAMS/CAPS/IDENTITY 必须模块顶层字面常量。错误当场返回。"""
    return _j(service.save_script(id, code))


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
    color/shape(circle|square|arrowUp|arrowDown)/text。
    越界处理：time 超出已加载K线范围的标记会被**丢弃**（不静默），并在返回的
    dropped 数组中列出（含 time 与原因），便于调用者自我纠正。"""
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
                   instances: str = None) -> str:
    """获取区间指标值，范围逻辑同 get_kline（不传=当前view）。
    instances 逗号分隔按 inst_id 过滤（如 'macd,sma_2'），不传=全部。"""
    inst_list = [x.strip() for x in instances.split(",") if x.strip()] if instances else None
    return _j(service.get_indicators(board_id, timeframe, start, end, inst_list))

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
    发送 snapshot_request 后等待 wait 秒再读取最新快照。
    无浏览器在线时明确报 NO_BROWSER（不回退磁盘旧图，防僵尸快照误导）。"""
    from .api.common import ws_manager
    if not ws_manager.active:
        return {"error": "NO_BROWSER: 无浏览器连接 /ws，快照需在线前端；"
                         "请先打开 Web UI（或确认目标标签页存活）再截图"}
    service.notify({"type": "snapshot_request", "board_id": board_id, "timeframe": timeframe})
    await asyncio.sleep(wait)
    return _snapshot_content(board_id, timeframe)


@mcp.tool()
def get_snapshot(board_id: str = None, timeframe: str = None):
    """读取最新快照（图片+路径）。快照由浏览器截图上传产生。"""
    return _snapshot_content(board_id, timeframe)





@mcp.tool()
def list_skills() -> str:
    """列出可用 skills（name+description）。先用它发现，再用 load_skill 读全文。
    skills 随项目仓库发布，教 agent 编写合法脚本/使用引导呈现等领域知识。"""
    return _j(_skills.list_skills())


@mcp.tool()
def load_skill(name: str) -> str:
    """加载指定 skill 的完整文档（如 script-authoring / ai-walkthrough）。
    写新指标/数据源脚本前请先 load_skill('script-authoring')。"""
    return _j(_skills.load_skill(name))
