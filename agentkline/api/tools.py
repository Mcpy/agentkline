"""
v0.4.1 防漂移①：REST/MCP 单一注册源。
一个能力 = 一个函数 + 一个 @api_tool 装饰器；routes.py 与 mcp_server.py 从 REGISTRY 生成，手工镜像退役。

绑定约定（文档化，前端/e2e 同守）：
- POST/PUT：除 path 参数外**全部参数来自 JSON body 扁平对象**（board_id/timeframe 也在 body）；
- GET/DELETE：path 参数 + query 标量；
- dict/list 类型参数在 body 中即对应键；MCP 侧同签名即工具 schema。
错误约定：函数返回 {"error": ...}，注册层按 err_status 映射 HTTP 码（默认 400；_err 处理 SOURCE_LOCKED=409 等）。
豁免清单（手工出口，注释明示）：页面/WS/快照上传(FileResponse+base64)/take_snapshot,get_snapshot(MCP-only 二进制)。
"""
import inspect
from datetime import datetime
from typing import Optional

from .common import service, _resolve, _err, SCRIPTS_DIR
from ..core import skills as _skills

REGISTRY = []


def api_tool(group="read", method="GET", path="", mcp=True, rest=True, err_status=400,
           aliases=None, rest_guard=None, err_passthrough=False):
    def deco(fn):
        fn._api = {"group": group, "method": method, "path": path, "mcp": mcp,
                   "rest": rest, "err_status": err_status, "aliases": aliases or {},
                   "rest_guard": rest_guard, "err_passthrough": err_passthrough,
                   "params": list(inspect.signature(fn).parameters)}
        REGISTRY.append(fn)
        return fn
    return deco


def ports_for(group):
    return ["web", "agent"] if group in ("read", "user_write", "manage") else ["agent"]


# ============ read ============
@api_tool(group="read", path="/api/boards")
def list_boards():
    """列出所有画板"""
    return service.list_boards()


@api_tool(group="read", path="/api/skills")
def list_skills():
    """列出可用 skills（name+description）。先用它发现，再用 load_skill 读全文。"""
    return {"skills": _skills.list_skills()}


@api_tool(group="read", path="/api/skills/{name}", err_status=404)
def load_skill(name: str):
    """加载指定 skill 的完整文档（如 script-authoring / ai-walkthrough）。"""
    return _skills.load_skill(name)


@api_tool(group="read", path="/api/board/{board_id}/interval_options", mcp=False, err_status=404)
def interval_options(board_id: str):
    """周期"+"按钮数据：{online, supported, current, addable}；仅实时源 online=True"""
    return service.interval_options(board_id)


@api_tool(group="read", path="/api/search")
def search_symbols(q: str = "", refresh: bool = False):
    """标的搜索（P1）：返回 rows=[{symbol, source, display, has_board}]，行=完整二元组(源,裸符号)；
    has_board=True=该二元组已有现场(●徽标，防重复建板)。索引=CAPS.symbols 源首用全量+TTL 日级，
    搜索永不穿透交易所；refresh=true 强刷索引。无徽章源用 @源名 裸符号 直配。"""
    return service.search_symbols(q, refresh)


@api_tool(group="read", path="/api/board/{board_id}", err_status=404)
def switch_board(board_id: str):
    """切换当前画板，前端随之显示该画板（广播其默认周期状态）；用于 AI 主动展示。
    增删查工具仍需显式传 board_id。"""
    return service.switch_board(board_id)


@api_tool(group="read", path="/api/board/{board_id}/timeframes", err_status=404)
def list_timeframes(board_id: str):
    """列出画板的时间周期"""
    return service.list_timeframes(board_id)


@api_tool(group="read", path="/api/board/{board_id}/timeframe/{timeframe}", err_status=404)
def switch_timeframe(board_id: str, timeframe: str):
    """切换当前时间周期，前端随之显示该周期（广播该周期状态）；用于 AI 主动展示，类比 switch_board。
    取数等工具仍需显式传 timeframe。"""
    return service.switch_timeframe(board_id, timeframe)


@api_tool(group="read", path="/api/state", mcp=False)
def get_state(board_id: Optional[str] = None, timeframe: Optional[str] = None):
    """全量状态切片（调试/兼容面）；常规取数请用 overview/get_kline/get_indicators"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.get_state(board_id, timeframe)


@api_tool(group="read", path="/api/kline", err_status=400)
def get_kline(board_id: Optional[str] = None, timeframe: Optional[str] = None,
              start: Optional[int] = None, end: Optional[int] = None):
    """获取区间K线（含成交量）。不传start/end=用户当前view窗口。
    start/end 为毫秒时间戳 epoch_ms（如 1755000000000）；若误传秒（<1e11）会自动×1000。"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.get_kline(board_id, timeframe, start, end)


@api_tool(group="read", path="/api/indicators", err_status=400)
def get_indicators(board_id: Optional[str] = None, timeframe: Optional[str] = None,
                   start: Optional[int] = None, end: Optional[int] = None,
                   instances: Optional[str] = None):
    """获取区间指标值，范围逻辑同 get_kline（不传=当前view）。
    instances 逗号分隔按 inst_id 过滤（如 'macd,sma_2'），不传=全部。"""
    board_id, timeframe = _resolve(board_id, timeframe)
    inst_list = [x.strip() for x in instances.split(",") if x.strip()] if instances else None
    return service.get_indicators(board_id, timeframe, start, end, inst_list)


@api_tool(group="read", path="/api/markers", err_status=404)
def get_markers(board_id: Optional[str] = None, timeframe: Optional[str] = None):
    """读取主图标记（买卖点等）。返回标记数组，字段同 set_markers（time/position/color/shape/text）；
    设置/覆盖用 set_markers。"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.get_markers(board_id, timeframe)


@api_tool(group="read", path="/api/overview", err_status=404)
def overview(board_id: Optional[str] = None, timeframe: Optional[str] = None):
    """轻量结构总览：品种/周期/数据源/指标元信息/副图名/画线与标记计数等，
    不含K线与指标数值数组（省token）。探查'图上有什么'首选本工具；取数用 get_kline/get_indicators。"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.get_overview(board_id, timeframe)


@api_tool(group="read", path="/api/subplots")
def list_subplots(board_id: Optional[str] = None, timeframe: Optional[str] = None):
    """列出画板+周期的所有副图"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.list_subplots(board_id, timeframe)


@api_tool(group="read", path="/api/drawings")
def list_drawings(board_id: Optional[str] = None, timeframe: Optional[str] = None):
    """列出画板+周期的所有划线"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.list_drawings(board_id, timeframe)


@api_tool(group="read", path="/api/config", mcp=False)
def get_config():
    """服务配置快照：scripts_dir（custom 根路径）与版本号"""
    return {"scripts_dir": str(SCRIPTS_DIR), "version": service.VERSION}


@api_tool(group="read", path="/api/view")
def get_current_view():
    """获取用户当前视图（画板/周期/可见时间窗口），由前端上报"""
    return service.current_view or {}


# ============ user_write ============
@api_tool(group="user_write", method="POST", path="/api/board", err_status=400,
           aliases={"board_id": "id"}, rest_guard="lock")
def create_board(board_id: str, name: Optional[str] = None, intervals: Optional[list] = None,
                 symbol: Optional[str] = None, source: Optional[str] = None,
                 params: Optional[dict] = None, poll_s: Optional[int] = None):
    """创建画板。intervals 为初始周期列表（如 ["1d","4h"]），首个为默认周期。
    给 symbol+source = 建板即锁（一标的一板：source_lock={script, identity 快照}），并自动配置默认周期；
    皆无 = 裸板（未锁定初始态，仅 AI 可建），首配 set_kline_source 时锁定。
    换标的/换源被锁禁掉 → 请新建画板（撞锁返回 SOURCE_LOCKED+suggestion）。"""
    return service.create_board(board_id, name, intervals, symbol, source, params, poll_s)


@api_tool(group="exec", method="POST", path="/api/board/empty", mcp=False, err_status=400,
           aliases={"board_id": "id"})
def create_empty_board(board_id: str, name: Optional[str] = None, intervals: Optional[list] = None):
    """裸板（未锁定初始态）：仅 agent 端口 REST。用户侧无空板（建板即锁/删光落引导页）；
    MCP 侧用 create_board 不传 symbol/source。"""
    return service.create_board(board_id, name, intervals)


@api_tool(group="user_write", method="POST", path="/api/drawing", err_status=400)
def add_drawing(board_id: Optional[str] = None, timeframe: Optional[str] = None, type: str = "hline",
                points: Optional[list] = None, color: str = "#ef5350", line_width: int = 2,
                line_style: str = "solid", text: str = ""):
    """画线。type: hline(水平,points=[{price}]) / trend(趋势,points=[{time,price},{time,price}])。
    time 为毫秒时间戳。"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.add_drawing(board_id, timeframe, {"type": type, "points": points, "color": color,
                                                     "line_width": line_width, "line_style": line_style,
                                                     "text": text})


@api_tool(group="user_write", method="POST", path="/api/drawing/{drawing_id}", err_status=404)
def update_drawing(board_id: Optional[str] = None, timeframe: Optional[str] = None, drawing_id: str = "",
                   visible: Optional[bool] = None, color: Optional[str] = None,
                   line_width: Optional[int] = None, line_style: Optional[str] = None,
                   text: Optional[str] = None):
    """更新划线：visible(显隐)/color/line_width/line_style(solid|dashed|dotted)/text"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.update_drawing(board_id, timeframe, drawing_id,
                                  {"visible": visible, "color": color, "line_width": line_width,
                                   "line_style": line_style, "text": text})


@api_tool(group="user_write", method="DELETE", path="/api/drawing/{drawing_id}", err_status=404)
def delete_drawing(board_id: Optional[str] = None, timeframe: Optional[str] = None, drawing_id: str = ""):
    """删除划线"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.delete_drawing(board_id, timeframe, drawing_id)


@api_tool(group="user_write", method="POST", path="/api/board/{board_id}/timeframe/{timeframe}/backfill",
           err_passthrough=True)
def backfill(board_id: str, timeframe: str, limit: int = 200):
    """向左补充更早的历史K线（前插到现有最早一根之前）。
    场景：图表向左滚动、已加载的最早K线不够看时，回溯拉取更早行情（前端左滑也会自动触发）。
    前提：该画板/周期已配置数据源，且其 CAPS.backfill=True（如 datasource/ccxt_binance、datasource/mock_btc）；
    无 backfill 徽章（如 datasource/csv）返回 prepended=0 并注明 NO_BACKFILL。
    返回：prepended(本次前插根数) / total(当前总根数)。"""
    return service.backfill(board_id, timeframe, limit)


@api_tool(group="user_write", method="POST", path="/api/view", mcp=False)
def report_view(board_id: Optional[str] = None, timeframe: Optional[str] = None,
                from_time: Optional[int] = None, to_time: Optional[int] = None):
    """前端上报当前视图（画板/周期/可见窗口）；AI 读盘用 get_current_view。
    v0.4.3 bug5：board_id 空 = 清空视图（tab 隐藏/无前景观众），防僵尸后台 tab 覆盖全局 current_view"""
    if not board_id:
        service.current_view = {}
        return {"status": "ok"}
    service.current_view = {"board_id": board_id, "timeframe": timeframe,
                            "from": from_time, "to": to_time,
                            "updated_at": datetime.now().isoformat()}
    # v0.4.3 bug5 根治：视图命中即唤醒该槽长睡 loop（否则新板/重连后首睡 300s 档，价格冻至多 5 分钟）
    if board_id and timeframe:
        service.datasource.poke(board_id, timeframe)
    return {"status": "ok"}


@api_tool(group="user_write", method="POST", path="/api/markers", err_status=400)
def set_markers(board_id: Optional[str] = None, timeframe: Optional[str] = None,
                markers: Optional[list] = None):
    """在K线主图设置标记（覆盖式，替换该周期已有全部标记；读取用 get_markers）。
    单个标记字段：time(毫秒，需与某根K线bar时间对齐)/position(aboveBar|belowBar|inBar)/
    color/shape(circle|square|arrowUp|arrowDown)/text。
    越界处理：time 超出已加载K线范围的标记会被**丢弃**（不静默），并在返回的
    dropped 数组中列出（含 time 与原因），便于调用者自我纠正。"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.set_markers(board_id, timeframe, markers or [])


@api_tool(group="user_write", method="POST", path="/api/board/{board_id}/timeframe", err_status=400)
def create_timeframe(board_id: str, interval: str):
    """给画板添加时间周期（如 1d/4h/1h）。已锁定在线板：新周期槽由系统自动注入
    {script, identity+interval} 直接出图；离线/裸板新槽为空白待配。"""
    return service.create_timeframe(board_id, interval)


# ============ manage ============
@api_tool(group="manage", method="DELETE", path="/api/indicator/{inst_id}", err_status=404)
def delete_indicator(board_id: Optional[str] = None, timeframe: Optional[str] = None, inst_id: str = ""):
    """按 inst_id 删除指标实例（登记处+各周期物化一次删净；现有 inst_id 见 overview）。"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.delete_indicator(board_id, timeframe, inst_id)


@api_tool(group="manage", method="PUT", path="/api/indicator/{inst_id}", err_status=400)
def update_indicator(board_id: Optional[str] = None, timeframe: Optional[str] = None, inst_id: str = "",
                     params: Optional[dict] = None, style: Optional[dict] = None,
                     lines_style: Optional[dict] = None, display_name: Optional[str] = None,
                     auto_label: Optional[bool] = None):
    """更新指标实例（inst_id 把手）。params=新参数(重声明配方触发重算)；style=整体样式；
    lines_style={线名:{color,lineWidth,lineStyle}}；display_name=覆盖显示名；
    auto_label=true 恢复自动命名。blob 改 params 报错。"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.update_indicator(board_id, timeframe, inst_id, params, style,
                                    lines_style, display_name, auto_label)


@api_tool(group="manage", method="DELETE", path="/api/board/{board_id}", err_status=404)
def delete_board(board_id: str):
    """删除画板（连同其所有周期、K线、指标、副图与画线，不可恢复）。"""
    return service.delete_board(board_id)


@api_tool(group="manage", method="DELETE", path="/api/board/{board_id}/timeframe/{timeframe}", err_status=404)
def delete_timeframe(board_id: str, timeframe: str):
    """删除时间周期（连同其K线/指标/画线）。若删的是当前周期，自动回退到默认周期。"""
    return service.delete_timeframe(board_id, timeframe)


# ============ exec ============
@api_tool(group="exec", path="/api/scripts")
def list_scripts():
    """列出全部脚本（双根：builtin 内置只读 / custom 可写）。
    返回 [{id, kind, source, display, desc, params, caps, identity}]：
    id=kind/name 是一切引用的唯一格式；caps=能力徽章（backfill/symbols/ticker）；
    identity=板锁身份键（如 ["symbol"]）。写新脚本前先读 load_skill('script-authoring')。"""
    return {"scripts": service.script_engine.list_scripts()}


@api_tool(group="exec", method="POST", path="/api/scripts", err_status=400)
def save_script(id: str, code: str):
    """保存自定义脚本到 custom 根（保存即校验：main 存在/CAPS 一致性/字面元数据合法）。
    id=kind/name（kind∈datasource/indicator/strategy）；内置脚本不可改。
    契约：datasource main(params[, until])→bars；indicator main(params, ohlcv)→values|{values,lines,markers}；
    元数据 NAME/DESC/PARAMS/CAPS/IDENTITY 必须模块顶层字面常量。错误当场返回。"""
    if not id or not code:
        return {"error": "SAVE_EMPTY: 需要 id 与 code"}
    return service.save_script(id, code)


@api_tool(group="exec", method="POST", path="/api/view/range", err_status=400)
def set_view_range(board_id: Optional[str] = None, timeframe: Optional[str] = None,
                   from_time: Optional[int] = None, to_time: Optional[int] = None):
    """让前端聚焦到指定时间窗口（AI 主动把画面拉到某段时间，如回测亏损区间）。
    需先 switch_board/switch_timeframe 切到目标板/周期（前端只在当前显示的板/周期上应用）。
    from_time/to_time 为毫秒时间戳（误传秒自动×1000），需 from<to 且在已加载数据范围内。
    建议顺序：set_markers/add_drawing → switch_board → switch_timeframe → set_view_range。"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.set_view_range(board_id, timeframe, from_time, to_time)


@api_tool(group="exec", method="POST", path="/api/run-script", err_status=500)
def run_script(script: str, params: Optional[dict] = None):
    """执行脚本并返回结果（窄身：图上不留痕，save_as 已废除）。
    script 为 id（kind/name，如 indicator/macd、datasource/mock_btc）；裸文件名已废弃。
    指标上图 = save_script + add_indicator(script=...)；K线入图 = set_kline_source 配方。"""
    return service.run_script(script, params)


@api_tool(group="user_write", method="POST", path="/api/indicator", err_status=400)  # v0.4.3：用户面开关入口（传统面板式），exec→user_write 同 create_timeframe 先例
def add_indicator(board_id: Optional[str] = None, timeframe: Optional[str] = None,
                  inst_id: Optional[str] = None, values: Optional[list] = None,
                  subplot: Optional[str] = None, style: Optional[dict] = None,
                  lines: Optional[list] = None, script: Optional[str] = None,
                  params: Optional[dict] = None, scope: Optional[str] = None,
                  display_name: Optional[str] = None):
    """加指标（统一入口，inst_id 把手）。
    - 计算型 recipe：给 script（id 格式 kind/name，如 'indicator/macd'）+params，随K线自动重算
    - 冻结 blob：给 values 或多线 lines，钉死本周期（传 scope 报 BLOB_SCOPE）
    - inst_id 撞名报 INST_EXISTS；不传自动 macd_2 式生成；两者皆无报 EMPTY_INDICATOR。"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.add_indicator(board_id, timeframe, inst_id=inst_id, values=values,
                                 subplot=subplot, style=style, markers=None, lines=lines,
                                 script=script, params=params, scope=scope,
                                 display_name=display_name)


@api_tool(group="exec", method="POST", path="/api/indicator/refresh/{inst_id}", mcp=False, err_status=400)
def refresh_indicator(board_id: Optional[str] = None, timeframe: Optional[str] = None, inst_id: str = ""):
    """强制重算 recipe 指标实例（换参重声明之外的手动刷新出口）"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.refresh_indicator(board_id, timeframe, inst_id)


@api_tool(group="exec", method="PUT", path="/api/board/{board_id}", mcp=False, err_status=404)
def update_board(board_id: str, patch: Optional[dict] = None):
    """更新画板展示属性（name 等）；锁字段不可改"""
    return service.update_board(board_id, patch or {})


@api_tool(group="exec", method="PUT", path="/api/board/{board_id}/timeframe/{timeframe}/kline_source", err_status=400)
def set_kline_source(board_id: str, timeframe: str, script: str,
                     params: Optional[dict] = None, poll_s: Optional[int] = None):
    """声明式配置 K 线来源（幂等，PUT 语义）。script 为 id（kind/name，如 datasource/ccxt_binance）。
    空板首配=锁定；已锁板须 script 与 IDENTITY 键全等，违则 SOURCE_LOCKED（带 suggestion 一键改道建板）。
    IDENTITY 之外 params=操作参数自由改（改即重拉）；仅 poll_s 变=不碰数据；poll_s>0 轮询实时刷新。
    附指标请用 add_indicator（打包参已废除）。"""
    return service.set_kline_source(board_id, timeframe, script, params, poll_s)


@api_tool(group="exec", path="/api/board/{board_id}/timeframe/{timeframe}/kline_source", mcp=False)
def get_kline_source(board_id: str, timeframe: str):
    """读取槽配置 {script, params, mode, poll_s}（诊断用）"""
    return service.get_kline_source(board_id, timeframe)


@api_tool(group="exec", method="POST", path="/api/board/{board_id}/timeframe/{timeframe}/refresh", mcp=False)
def refresh_timeframe(board_id: str, timeframe: str):
    """手动重拉该槽 K 线（不等轮询）"""
    return service.refresh_timeframe(board_id, timeframe)


@api_tool(group="exec", method="POST", path="/api/subplot", err_status=400)
def create_subplot(board_id: Optional[str] = None, timeframe: Optional[str] = None,
                   name: str = "", height: int = 150, title: Optional[str] = None):
    """创建副图——主图下方的独立小面板，用于放置指标（如 MACD/KDJ/成交量）。
    建好后用 add_indicator(subplot=名称) 把指标放进该副图；查看用 list_subplots。"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.create_subplot(board_id, timeframe, name, height, title)


@api_tool(group="exec", method="PUT", path="/api/subplot/{name}", mcp=False, err_status=404)
def update_subplot(board_id: Optional[str] = None, timeframe: Optional[str] = None,
                   name: str = "", height: Optional[int] = None, title: Optional[str] = None):
    """更新副图高度/标题"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.update_subplot(board_id, timeframe, name, height, title)


@api_tool(group="exec", method="DELETE", path="/api/subplot/{name}", err_status=404)
def delete_subplot(board_id: Optional[str] = None, timeframe: Optional[str] = None, name: str = ""):
    """删除副图（连同其上指标）"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.delete_subplot(board_id, timeframe, name)


# ============ 雷达（v0.4.1） ============
@api_tool(group="read", path="/api/watchlist")
def watchlist_list():
    """雷达面板数据：groups[]→rows[]，每行含最新价/涨跌幅/三态(visible/hidden/watch)/未读心跳/●现场徽标"""
    return service.watchlist.list_watchlist()


@api_tool(group="user_write", method="POST", path="/api/watchlist/rows", err_status=400)
def watchlist_add(source: str, symbol: str, group_id: str = None):
    """加入雷达盯盘（幂等）。源须声明 CAPS.ticker，违则 TICKER_UNSUPPORTED；group_id 可选（默认组 default）"""
    return service.watchlist.add_row(source, symbol, group_id)


@api_tool(group="user_write", method="DELETE", path="/api/watchlist/rows", err_status=404)
def watchlist_remove(source: str, symbol: str):
    """移出雷达盯盘"""
    return service.watchlist.remove_row(source, symbol)


@api_tool(group="user_write", method="POST", path="/api/watchlist/groups", err_status=400)
def watchlist_group_add(name: str):
    """雷达新建分组（重名 GROUP_EXISTS）"""
    return service.watchlist.add_group(name)


@api_tool(group="user_write", method="PUT", path="/api/watchlist/groups/rename", err_status=400)
def watchlist_group_rename(group_id: str, name: str):
    """雷达分组改名（默认组 GROUP_PROTECTED）"""
    return service.watchlist.rename_group(group_id, name)


@api_tool(group="user_write", method="DELETE", path="/api/watchlist/groups", err_status=400)
def watchlist_group_remove(group_id: str):
    """删除雷达分组——行回落默认组，不级联删行（默认组 GROUP_PROTECTED）"""
    return service.watchlist.remove_group(group_id)


@api_tool(group="user_write", method="PUT", path="/api/watchlist/move", err_status=400)
def watchlist_move(source: str, symbol: str, group_id: str, index: int = None):
    """雷达行移组+定位（index=None 追加组尾；拖拽落定调用）"""
    return service.watchlist.move_row(source, symbol, group_id, index)


@api_tool(group="read", path="/api/quotes")
def get_quotes():
    """全行 quotes 快照（AI 读盘用）；面板实时走 WS quotes_update"""
    return service.watchlist.quotes_snapshot()


# ============ MCP-only（二进制/图片，REST 豁免） ============
@api_tool(group="exec", method="POST", path="", rest=False, mcp=False)
def take_snapshot(board_id: Optional[str] = None, timeframe: Optional[str] = None, wait: float = 1.5,
                  allow_stale: bool = False):
    """触发前端截图并返回图片+路径。需有浏览器连着 /ws。
    发送 snapshot_request 后等待 wait 秒再读取最新快照。
    无浏览器在线时明确报 NO_BROWSER（不回退磁盘旧图，防僵尸快照误导）；
    allow_stale=true 显式接受最近磁盘快照（带 stale:true + stale_since）。"""
    return service.take_snapshot(board_id, timeframe, wait, allow_stale)


@api_tool(group="exec", method="POST", path="", rest=False, mcp=False)
def get_snapshot(board_id: Optional[str] = None, timeframe: Optional[str] = None):
    """读取最新快照（图片+路径）。快照由浏览器截图上传产生。"""
    return service.get_snapshot(board_id, timeframe)
