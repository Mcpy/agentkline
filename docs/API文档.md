# AgentKline API 文档

> 版本：v0.4.0 ｜ 适用：FastAPI（REST + WebSocket）与 MCP server
> 破坏性硬切版本：无兼容层。旧路径（/api/ohlcv、/api/load-csv、/history、datasource 端点、indicator/update 杂交路径）一律 404/405。
> 机器可读附录：`python scripts/gen_api_ref.py` 可从运行中服务生成 REST 路由表 + MCP 工具表（防漂移）。

## 0. 通用约定

- **双端口**：web `:8765`（浏览器，无鉴权）／agent `:8766`（AI agent，全量 Bearer）。
  web 挂载：页面/静态/WS/read/user_write/manage；agent 挂载：read/user_write/exec/manage + `/mcp`。
- **id 格式**：脚本引用一律 `kind/name`（kind∈datasource|indicator|strategy），裸文件名 400 `SCRIPT_BAD_ID`。
- **时间**：服务端一律毫秒；区间参数 start/end 接受秒级自适应（<1e11 视为秒）。
- **WS 信封（v0.4 硬切）**：所有消息 `{"v":1,"type":...,"seq":<每连接自增>,"ts":<服务端ms>,"payload":{...}}`；
  业务字段全在 payload；`init`/`pong` 同款式；seq 仅排障（无 ACK，恢复=重连重拉 init）。
- **先写状态后广播**：任何广播发出前服务端状态已落，读后写无竞态。
- 错误：HTTP 400 通用；409=`SOURCE_LOCKED`（detail 带 `{error, code, suggestion}`）；404 资源/退役端点。

## 1. 画板管理

| 方法 | 路径 | 端口 | 说明 |
|---|---|---|---|
| POST | `/api/board` | web+agent | **建板即锁**：body `{id,name?,intervals?,symbol,source,params?,poll_s?}`；缺 symbol/source=400 `LOCK_REQUIRES_SOURCE` |
| POST | `/api/board/empty` | agent | 裸板（未锁定初始态，仅 AI）：`{id,name?,intervals?}` |
| GET | `/api/boards` | read | 列表含 `source_lock/locked/identity_display` |
| GET | `/api/board/{id}` | read | 切换（广播 board_switch 带窗口化状态） |
| PUT | `/api/board/{id}` | manage | 改名等 |
| DELETE | `/api/board/{id}` | manage | 删板（停该板所有槽轮询+清配置） |

板锁：`source_lock={script, identity:{IDENTITY键:值}}`；锁定后不可变；换标的/换源=新建画板。

## 2. 时间周期管理

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/board/{id}/timeframe` | `{interval}`；**已锁定在线板自动注入** `{script, identity+interval}` 配置新槽直接出图 |
| GET | `/api/board/{id}/timeframes` | 列表 |
| GET | `/api/board/{id}/timeframe/{tf}` | 切换周期（广播 timeframe_switch 带窗口化状态） |
| DELETE | `/api/board/{id}/timeframe/{tf}` | 删周期 |

## 3. K 线来源 / 回溯（原 datasource/history 硬切）

| 方法 | 路径 | 端口 | 说明 |
|---|---|---|---|
| PUT | `/api/board/{b}/timeframe/{tf}/kline_source` | user_write | 声明式幂等配置 `{script,params?,poll_s?}`：空板首配=锁；已锁板全槽全等校验违则 409；配置全同=noop；仅 poll_s 变=poll_only 不碰数据；IDENTITY 外参数变=重拉 |
| GET | `/api/board/{b}/timeframe/{tf}/kline_source` | read | 槽配置+运行态 `{script,params,mode,poll_s,status{last_error,last_fetch,next_due,started_at}}`（REST-only，不进 MCP） |
| POST | `/api/board/{b}/timeframe/{tf}/backfill` | user_write | 向左补历史 `{limit?}`；CAPS.backfill 门控，无徽章=`NO_BACKFILL`；返回 `{prepended,total,dropped?}` |

退役（404）：`POST /api/ohlcv`、`POST /api/load-csv`、`DELETE .../datasource`、`POST .../history`。
CSV 入图 = 内置 `datasource/csv` 脚本（path 归操作参数，IDENTITY=[]）。

## 4. 指标（inst_id 实例模型）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/indicator` | body `{inst_id?,script?,params?,values?,lines?,markers?,subplot?,style?,scope?,display_name?}`；script=recipe／values|lines=blob（传 scope 报 `BLOB_SCOPE`）；inst_id 撞名 `INST_EXISTS`；不传自动 `macd_2` 式；皆无 `EMPTY_INDICATOR` |
| PUT | `/api/indicator/{inst_id}` | 统一更新：params=重声明配方重算；style/lines_style=不重算；display_name 覆盖／auto_label 恢复 |
| POST | `/api/indicator/refresh/{inst_id}` | recipe 手动重算 |
| DELETE | `/api/indicator/{inst_id}` | 登记处+各周期物化一次删净 |
| GET | `/api/indicators` | 值区间切片；`instances=` 逗号分隔按 inst_id 过滤；默认当前 view 窗口 |

实例两血统：recipe（锚配方，随 K 线重算，scope=board|timeframe）／blob（冻结值，钉死单周期；backfill 前插自动头部补 None 保对齐）。

## 5. 标记 / 划线 / 副图

- `POST /api/markers` `{markers:[...]}`：越界 time 丢弃+`dropped` 回报（不静默）；`GET /api/markers` 读。
- 划线：`POST /api/drawing`、`POST /api/drawing/{id}`（更新）、`DELETE /api/drawing/{id}`、`GET /api/drawings`（hline/trend）。
- 副图：`POST /api/subplot`、`PUT /api/subplot/{name}`、`DELETE /api/subplot/{name}`、`GET /api/subplots`；
  删副图连带删除 target 其上的指标实例。

## 6. 脚本 / 搜索 / skills

| 方法 | 路径 | 端口 | 说明 |
|---|---|---|---|
| GET | `/api/scripts` | exec | 双根脚本表 `[{id,kind,source,display,desc,params,caps,identity}]` |
| POST | `/api/scripts` | exec | `save_script`：`{id,code}` 只写 custom，保存即校验（CAPS_MISMATCH/SAVE_SYNTAX/SAVE_NO_MAIN/SAVE_EMPTY） |
| POST | `/api/run-script` | exec | 窄身 `{script,params}`：只执行返回，图上不留痕 |
| GET | `/api/search` | read | 标的搜索 `?q=&refresh=`：rows=`[{symbol,source,display,has_board}]`；索引=CAPS.symbols 源首用全量+TTL 日级；搜索不穿透交易所 |
| GET | `/api/skills` / `/api/skills/{name}` | read | skills 列表/全文（MCP 薄镜像） |

## 7. 状态 / 只读 / 视图

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/overview` | 结构总览：source_lock/locked/槽配置+状态/指标实例元信息(kind/script/scope/target/display/dynamic)/副图/计数；**无数值数组** |
| GET | `/api/kline` | 纯 K 线+成交量区间切片（不传=当前 view） |
| GET | `/api/view` ／ POST `/api/view` | 读/上报用户真实视图（上报仅 web 端口，浏览器无 token） |
| POST | `/api/view/range` | set_view_range 聚焦 `{from,to}` |
| GET | `/api/state` | 渲染快照（WS init 同构，窗口化）；agent 建议改 overview+kline |
| GET | `/api/config` | scripts_dir/version |

## 8. WebSocket（`/ws`，web 端口）

信封见 §0。事件表（payload 字段省略 board_id/timeframe 公共键）：

| type | payload 要点 |
|---|---|
| init | `{data(窗口化状态), boards, board_id, timeframe}` |
| ohlcv_update | **差量**：`{prepended:[bars], appended:[bars], updated:[bars], markers?}`（前端按 ts 合并） |
| indicator_add / indicator_update | `{inst_id, kind, script, params, scope, subplot, style, lines_style, display_name, values, lines, markers}` |
| indicator_remove | `{inst_id}` |
| markers_update / drawing_add / drawing_update / drawing_remove | 同 v0.3 语义 |
| board_create / board_remove / board_switch | board_switch 带窗口化 state |
| **board_locked** | `{source_lock}`（建板即锁/首配锁） |
| **kline_source_set** | `{script, params, poll_s}` |
| **scripts_changed** | `{id}`（save_script 后刷菜单） |
| timeframe_create/remove/switch、subplot_create/remove、view_set | 同 v0.3 语义 |
| datasource_error | `{error, retry_after}` |
| snapshot_request | 触发浏览器截图上传 |
| pong | ping 响应 |

## 9. 脚本约定（v0.4）

详见 `docs/脚本编写指南.md` 与 `skills/script-authoring.md`（agent 权威）。要点：
双根三层目录；id=kind/name；字面元数据族 NAME/DESC/PARAMS/CAPS/IDENTITY（ast 静态抽取零 exec）；
CAPS 声明⇒实现（backfill⇒until 参/symbols⇒list_symbols/ticker⇒ticker）；指标等长+warmup None+禁 NaN；
数据源 until 回溯可重放跨窗连续；单槽 max_bars_per_slot=50000 截旧+dropped；重算尾窗 max_window=5000；
数据家族单脚本分片范式；L1 沙箱自律。

## 10. MCP 工具（Streamable HTTP `/mcp`，agent 端口，35 个）

改名：set_datasource→**set_kline_source**；load_history→**backfill**；run_script 窄身；list_scripts payload 升级。
新增：save_script、search_symbols。换参：add/update/delete_indicator 与 get_indicators 换 inst_id/instances。
payload 调整：create_board(+symbol/source/params/poll_s)、create_timeframe、overview、list_boards。
原样保留 21 + list_skills/load_skill/get_kline/take_snapshot 等。
**MCP-only 判决**：take_snapshot（无 REST 触发）。**REST-only**：get_kline_source、/api/view 上报。
docstring 为单一真相；REST 为薄镜像；`test_e2e.py` 含两表面对齐断言。

## 11. 错误码

`SCRIPT_BAD_ID`(400) `SCRIPT_NOT_FOUND` `CAPS_MISMATCH` `SAVE_*`(400) `LOCK_REQUIRES_SOURCE`(400)
`LOCK_INCOMPLETE` `SOURCE_LOCKED`(409,+suggestion) `NO_BACKFILL` `INST_EXISTS` `BLOB_SCOPE`
`EMPTY_INDICATOR` `INDICATOR_BOTH` `NO_SYMBOLS_CAP`；越界 markers/bars 走 `dropped` 回报不报错。

## 12. 双端口与鉴权

web :8765 无鉴权（登录体系在规划池；**web 写端点=未来登录挂载面**）；agent :8766 全量 Bearer。
token：config `auth.token` 或 env `AGENTKLINE_TOKEN`。端口/host 可 config + env 覆盖。


## 12. 雷达（v0.4.1）

### 12.1 模型
- `groups[] → rows[]`（0.4.1 仅默认组；0.4.2 分组 UI 零重构接入）；行 = `{source, symbol}` 二元组。
- 行须源声明 `CAPS.ticker`（声明⇒实现 `ticker(params)→{price, ts, change_pct?, extra?}`，键白名单）；
  违则 `TICKER_UNSUPPORTED`(400)。
- **三态分发**（每 tick 判定）：`visible`=行即当前锁定板（发 `quote` 心跳事件，前端即时刷最新价）；
  `hidden`=有板非当前（缓存+未读心跳计数，切板清零）；`watch`=无板（仅面板）。
- quotes 轮询默认 5s（config `limits.quotes_poll_s`）；行级失败不炸整轮，连续 10 次失败标 `stale`。

### 12.2 接口
| REST | MCP | 说明 |
|---|---|---|
| GET /api/watchlist | watchlist_list | 组+行+quotes+state+●现场徽标+board_id |
| POST /api/watchlist/rows | watchlist_add | {source, symbol} 幂等 |
| DELETE /api/watchlist/rows | watchlist_remove | query: source, symbol |
| GET /api/quotes | get_quotes | 全行快照（AI 读盘） |

WS 事件：`quotes_update{rows[]}`（面板批量）/ `quote{board_id,price,change_pct,ts}`（visible 心跳）/
`watchlist_changed{groups[]}`（增删广播）。

### 12.3 REST 绑定约定（v0.4.1 生成器形态）
- **POST/PUT：除 path 参数外全部参数来自 JSON body 扁平对象**（board_id/timeframe 也在 body）；
- GET/DELETE：path 参数 + query 标量；
- 单一注册源 `api/tools.py` 的 `@api_tool`：REST 双端口路由与 MCP 工具同函数生成（防漂移①已偿还）；
  豁免清单：页面/WS/快照二进制（GET FileResponse、POST base64）与 take/get_snapshot（MCP-only 图块）。
- 表面不对称明示：REST `POST /api/board` 无 symbol+source 报 `LOCK_REQUIRES_SOURCE`（UX 门），
  MCP create_board 允许裸板（=agent REST /api/board/empty 同义）。


## 13. 性能模型（v0.4.1 四优化）

浏览器→server **零轮询**（全 WS 推送）；server→交易所请求预算如下：

### 13.1 可见性分级轮询（K线）
- `current_view`（前端 `POST /api/view` 上报）命中的 (板,周期) 槽 = 配置 `poll_s`；
- 非可见槽降频：`<=1h→60s`、`<=4h→120s`、`>=1d→300s`（`effective_poll_s`）；
- 切周期时槽数据老于降频窗 = **切即补拉**（`poke` 跳过本轮 sleep），用户无感；
- 读面：`GET /api/board/{id}/timeframe/{tf}/kline_source` 返回 `eff_poll_s`（当前生效间隔）；
- AI/REST 场景不上报 view 时全槽按降频跑（更省），切即补拉兜底。

### 13.2 雷达批量与去重
- 脚本可选 `tickers(params_list)->[quote]`（同序）；雷达每 tick **按源一次批量请求**
  （ccxt=fapi 24hr symbols 数组）；无实现回退逐行 `ticker()`；
- 雷达行=当前板且其槽 `last_fetch` 新鲜 → 用最新 bar close **合成 quote**（省独立请求）；
- 轮询 sleep 对齐 5s 网格（同刻请求合并连接复用）。

### 13.3 量级
3 板+5 行：240 req/分 → ≈46（↓81%）；10 板+20 行：840 → ≈170（↓80%）。


## 14. 雷达分组（v0.4.2）

- 结构：`watchlist_list` 返回 `groups[]→rows[]`（0.4.1 已铺，0.4.2 长出管理面）；
- 组管理四工具（MCP 39→43）：
  - `watchlist_group_add(name)` → 重名 `GROUP_EXISTS`(400)
  - `watchlist_group_rename(group_id, name)` / `watchlist_group_remove(group_id)`
    → 默认组 `GROUP_PROTECTED`；**删组=行回落默认组，不级联删行**
  - `watchlist_move(source, symbol, group_id, index=None)` → 移组+定位（拖拽落定调用）
- `watchlist_add` 扩 `group_id` 可选参（不传=default，向后兼容）；
- WS `watchlist_changed` 自 0.4.2 起携带**全组结构**（前端不再压平丢组信息）；
- 前端：组头（名称+行数+折叠，折叠态 localStorage）/ ⋮ 菜单（重命名/删除）/
  行右键"移到组→"/ HTML5 拖拽排序+跨组 / 面板过滤框 / hover 卡（24h 高/低/量，quote.extra）。


## 15. 快照 allow_stale（v0.4.2 B）

- `take_snapshot` 默认 fail-loud：无浏览器在线报 `NO_BROWSER`（不回退磁盘旧图，防僵尸快照误导）；
- `allow_stale=true`：显式接受最近磁盘快照，返回体带 `stale: true` + `stale_since`（文件时间戳），
  调用方自行判断可用性；MCP 返回的 TextContent 同样透传两字段。
