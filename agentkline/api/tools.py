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
    """加载指定 skill 的完整文档（如 datasource-authoring / indicator-authoring / ai-walkthrough）。"""
    return _skills.load_skill(name)


@api_tool(group="read", path="/api/board/{board_id}/interval_options", mcp=False, err_status=404)
def interval_options(board_id: str):
    """周期"+"按钮数据：{online, supported, current, addable}；仅实时源 online=True"""
    return service.interval_options(board_id)


@api_tool(group="read", path="/api/search")
def search_symbols(q: str = "", refresh: bool = False, source: Optional[str] = None):
    """搜索可交易标的。返回候选行，每行=一个"来源+符号"组合（has_board=True 表示该组合已有画板）。
    source=按数据源 id 筛选（如 'datasource/ashare_free'），在结果截断前过滤。
    用法：把选中行的 symbol 与 source 原样传给 create_board 建板。
    无搜索索引的来源（list_scripts 里 caps 不含 symbols 的）可跳过搜索、直接给 symbol+该 source 建板。"""
    return service.search_symbols(q, refresh, source)


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
    """新建一个图表画板。两种用法：
    ① 给 symbol+source = 开箱即用的实时板（自动配默认周期 [15m,1h,4h,1d,1w] ∩ 源支持档，初始显示 1d）；
    ② 都不给 = 空板，之后用 set_kline_source 配来源。
    同一 symbol+source 只允许一个画板，重复建会报 SOURCE_LOCKED 并指认现有板。intervals=初始周期列表，首个为默认。"""
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
    """向左补拉更早的历史 K 线（看更久远的行情用）。前提：该板数据源支持历史回补（list_scripts 里 caps 含 backfill；csv 类源不支持，返回 prepended=0）。返回本次补拉根数与当前总根数。"""
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
    """给画板加一个时间周期（如 '4h'）。实时板的新周期会自动取数出图；加完用 switch_timeframe 切过去看。"""
    return service.create_timeframe(board_id, interval)


# ============ manage ============
@api_tool(group="manage", method="DELETE", path="/api/indicator/{inst_id}", err_status=404)
def delete_indicator(board_id: Optional[str] = None, timeframe: Optional[str] = None, inst_id: str = ""):
    """把一个指标从图上移除（inst_id 从 overview 的 indicators 列表拿），一次删净不留残影。改参数请用 update_indicator，别删了重加。"""
    board_id, timeframe = _resolve(board_id, timeframe)
    return service.delete_indicator(board_id, timeframe, inst_id)


@api_tool(group="manage", method="PUT", path="/api/indicator/{inst_id}", err_status=400)
def update_indicator(board_id: Optional[str] = None, timeframe: Optional[str] = None, inst_id: str = "",
                     params: Optional[dict] = None, style: Optional[dict] = None,
                     lines_style: Optional[dict] = None, display_name: Optional[str] = None,
                     auto_label: Optional[bool] = None):
    """改一个已加指标（inst_id 从 overview 的 indicators 列表拿）。
    params=新参数，改后自动重算（如 MA 周期档、MACD 快慢慢期）；style/lines_style=颜色/线宽/线型；display_name=改显示名。
    要把指标从图上拿走用 delete_indicator。"""
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
    """列出全部可用脚本（内置+自定义）。每条含：id（引用格式如 'indicator/macd'，加指标/配源都用它）、
    desc、params（默认参数）、caps 能力（backfill=支持历史回补 / symbols=有搜索索引 / ticker=支持实时报价）。
    写自定义脚本前先按 kind 读 skill：datasource-authoring / indicator-authoring。"""
    return {"scripts": service.script_engine.list_scripts()}


@api_tool(group="exec", method="POST", path="/api/scripts", err_status=400)
def save_script(id: str, code: str):
    """保存自定义脚本到 custom 根（保存即校验：入口函数存在/能力声明一致/元数据合法）。
    **写之前先按 kind 读 skill：datasource-authoring / indicator-authoring**。id 格式 kind/name（如 indicator/my_macd）；
    同名 custom 覆盖同名内置（shadow 优先）。custom 根位置见 get_config，升级不丢（包外）。"""
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
    """跑一次脚本拿计算结果（**不上图、不留痕**）。适合：试算指标输出、拉一段数据源样本检查。要让指标上图用 add_indicator；要当画板数据源用 set_kline_source。"""
    return service.run_script(script, params)


@api_tool(group="user_write", method="POST", path="/api/indicator", err_status=400)  # v0.4.3：用户面开关入口（传统面板式），exec→user_write 同 create_timeframe 先例
def add_indicator(board_id: Optional[str] = None, timeframe: Optional[str] = None,
                  inst_id: Optional[str] = None, values: Optional[list] = None,
                  subplot: Optional[str] = None, style: Optional[dict] = None,
                  lines: Optional[list] = None, script: Optional[str] = None,
                  params: Optional[dict] = None, scope: Optional[str] = None,
                  display_name: Optional[str] = None):
    """加一个指标到图上。最常用：加内置指标，如 script='indicator/macd'（内置清单见 list_skills 之外的 list_scripts）。
    subplot 族（macd/kdj/rsi/obv）不传 subplot 时自动建副图放置；主图族（sma/ema/bb/sar）叠在主图。
    params=参数覆盖（如 {'periods':[10,20,60]} 换均线档）；inst_id 不传自动生成。
    返回 inst_id；改参/改样式用 update_indicator，从图上移除用 delete_indicator。"""
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
    """改画板的展示属性（目前仅展示名 name）。标的/来源等绑定信息不可改——要换请新建画板。"""
    return service.update_board(board_id, patch or {})


@api_tool(group="exec", method="PUT", path="/api/board/{board_id}/timeframe/{timeframe}/kline_source", err_status=400)
def set_kline_source(board_id: str, timeframe: str, script: str,
                     params: Optional[dict] = None, poll_s: Optional[int] = None):
    """给"画板+周期"配置或更换 K 线数据来源。
    注意：**一个画板只绑定一个标的+源**（首次配置即锁定）；换标的或换源请新建画板（create_board），
    对已锁板调本工具会报 SOURCE_LOCKED 并附建议。同板同源可改 params（如 limit）与轮询间隔 poll_s。
    常规流程：create_board(symbol=..., source=...) 一步到位，无需单独调本工具。"""
    return service.set_kline_source(board_id, timeframe, script, params, poll_s)


@api_tool(group="exec", path="/api/board/{board_id}/timeframe/{timeframe}/kline_source", mcp=False)
def get_kline_source(board_id: str, timeframe: str):
    """读画板某周期当前的 K 线来源配置（来源脚本/参数/轮询间隔），诊断用。"""
    return service.get_kline_source(board_id, timeframe)


@api_tool(group="exec", method="POST", path="/api/board/{board_id}/timeframe/{timeframe}/refresh", mcp=False)
def refresh_timeframe(board_id: str, timeframe: str):
    """立即重拉指定画板+周期的 K 线一次，不等自动轮询到点。改了数据源参数想马上看效果时用。"""
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
    """读雷达盯盘面板：groups[]→rows[]，每行=一个盯盘标的，含最新价/涨跌幅/显隐状态/是否有对应画板在现场。加盯用 watchlist_add，移组用 watchlist_move，建组用 watchlist_group_add。"""
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
    """删除雷达分组，**组内盯盘行一并级联删除**（行不保留，组删行没）；默认组不可删（GROUP_PROTECTED）。只想移走行请先用 watchlist_move。"""
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
