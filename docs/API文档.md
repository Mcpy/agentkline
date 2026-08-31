# AgentKline API 文档

> 版本：v0.3.2 ｜ 适用：FastAPI（REST + WebSocket）与 MCP server
> 基础地址（本地）：`http://localhost:8000`（或 `./start.sh <port>` 指定）

AgentKline 是一个交互式 K 线画板：多画板 × 多时间周期，全脚本化数据源/指标，实时轮询，
历史回溯，主副图联动。本文档覆盖 REST、WebSocket、脚本约定、MCP 工具与错误码。

---

## 0. 通用约定

### 0.1 多画板 / 多时间周期定位参数

除"画板/时间周期管理"类接口外，所有数据类接口都支持可选查询参数：

| 参数 | 含义 | 缺省行为 |
|------|------|----------|
| `board_id` | 指定画板 | 操作**当前画板** |
| `timeframe` | 指定时间周期 | 操作当前画板的**默认周期** |

> AI 自动化场景请**显式传** `board_id` + `timeframe`，不依赖用户手动切换。

### 0.2 时间戳

K 线 `timestamp` 为**毫秒**级 Unix 时间戳。前端按周期自动决定显示日期或日期+时间。

### 0.3 指标两种形态

- **单线**：`values: [null|number, ...]`（与 K 线索引对齐，null 表示该点无值）
- **多线**：`lines: [{name, type, values, style, markers?}, ...]`（如 BB 三轨、MACD 三线）

`type` 枚举：`line` / `area` / `baseline` / `histogram`（`bar` 为 histogram 的兼容别名）。

---

## 1. 画板管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/board` | 创建画板 `{id, name?, intervals?}` |
| GET | `/api/boards` | 列出所有画板 |
| GET | `/api/board/{id}` | 切换当前画板 |
| PUT | `/api/board/{id}` | 更新画板（重命名） |
| DELETE | `/api/board/{id}` | 删除画板 |

创建示例：
```json
POST /api/board
{"id": "btc", "name": "BTC", "intervals": ["1d", "4h"]}
```

## 2. 时间周期管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/board/{id}/timeframe` | 添加周期 `{interval}` |
| DELETE | `/api/board/{id}/timeframe/{tf}` | 删除周期（自动回退默认） |
| GET | `/api/board/{id}/timeframes` | 列出周期 |
| GET | `/api/board/{id}/timeframe/{tf}` | 切换周期 |

## 3. K 线 / 标记 / CSV

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/ohlcv?board_id&timeframe` | 直接推 K 线 `{ohlcv, markers?}` |
| POST | `/api/markers?board_id&timeframe` | 设置主图标记（覆盖式）`{markers}` |
| POST | `/api/load-csv?board_id&timeframe` | 加载 CSV `{path, time_col?}` |

K 线对象：`{timestamp, open, high, low, close, volume}`。
标记对象：`{time, position, color, shape, text}`（position: aboveBar/belowBar/inBar；shape: circle/square/arrowUp/arrowDown）。

## 4. 指标

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/indicator?board_id&timeframe` | **加指标（统一入口）**：`script` 计算型 / `values`·`lines` 现成型，`replace` 默认 true |
| DELETE | `/api/indicator/{name}?board_id&timeframe` | 删除指标 |
| POST | `/api/indicator/refresh/{name}?board_id&timeframe` | 手动重算（需有脚本） |
| POST | `/api/indicator/update/{name}?board_id&timeframe` | **统一更新**：改参数/样式/显示名（见下） |

**加指标两种模式**（二选一，皆无则 `400 EMPTY_INDICATOR`）：
- 计算型：给 `script`（如 `macd.py`）+`params`，服务端执行脚本算出值；例 `{"name":"MACD","script":"macd.py"}`
- 现成型：给 `values`（单线）或 `lines`（多线），直接落值

同名指标：`replace=true`（默认）覆盖；`replace=false` 且已存在 → `400 INDICATOR_EXISTS`。

### 4.1 指标统一更新 `POST /api/indicator/update/{name}`

```json
{ "params": {"period": 20},        // 可选：合并已存参数并重算（需有脚本）
  "style": {"color": "#f00", "lineWidth": 2, "lineStyle": 0},  // 可选：单线整体样式（不重算）
  "lines_style": {"DIF": {"color": "#f00"}},  // 可选：多线按线名逐线覆盖
  "display_name": "我的均线",        // 可选：自定义显示名（置 custom_label）
  "auto_label": true }             // 可选：恢复自动命名「根名(参数)」
```
- 画板级指标（scope=board）会同步到所有周期。
- 改 `params` 触发重算并广播 `indicator_update`；改样式不重算。
- 柱状图（histogram）样式可用 `autoColor:false` + `color` 固定单色；默认 `autoColor` 真=涨跌自动红绿。

## 5. 副图

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/subplot?board_id&timeframe` | 创建 `{name, height?, title?}` |
| PUT | `/api/subplot/{name}?board_id&timeframe` | 更新 `{height?, title?}` |
| DELETE | `/api/subplot/{name}?board_id&timeframe` | 删除（连同其上指标） |
| GET | `/api/subplots?board_id&timeframe` | 列出副图 |

## 6. 脚本 / 数据源 / 历史

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/scripts` | 列出可用指标/数据源脚本（与 MCP `list_scripts` 对齐） |
| POST | `/api/run-script?board_id&timeframe` | 执行脚本 `{path, params?, save_as?, indicator_name?, subplot?, scope?, display_name?}` |
| POST | `/api/board/{id}/timeframe/{tf}/datasource` | 配置数据源 `{path, params?, poll_interval?, indicators?}` |
| GET | `/api/board/{id}/timeframe/{tf}/datasource` | 查看数据源状态 |
| DELETE | `/api/board/{id}/timeframe/{tf}/datasource` | 停止数据源 |
| POST | `/api/board/{id}/timeframe/{tf}/refresh` | 手动刷新（重拉K线+重算指标） |
| POST | `/api/board/{id}/timeframe/{tf}/history` | 向左补更早K线（前插）`{limit?}`；需数据源支持 `until` 回溯，否则 `prepended=0` |

`run-script.save_as`：`ohlcv`（存K线）/ `indicator`（存指标）/ 不传（只返回数据）。
`run-script.scope`（仅 indicator）：`board`=作用于所有周期（默认）/ `timeframe`=仅本周期。
`run-script.display_name`：可选显示名覆盖；不传则按「根名(参数)」自动命名。
`datasource.poll_interval`：秒，>0 则轮询实时刷新；不传为一次性。

## 7. 状态 / 只读查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/overview?board_id&timeframe` | **轻量结构总览**：指标元信息/副图/数据源/画线·标记计数，无数值数组（省 token） |
| GET | `/api/kline?board_id&timeframe&start&end` | 纯 K 线（含成交量）区间切片；不传范围=当前 view |
| GET | `/api/indicators?board_id&timeframe&start&end&names` | 指标值区间切片；`names` 逗号分隔可指定一个/多个，默认全部 |
| GET | `/api/markers?board_id&timeframe` | 读取主图标记 |
| GET | `/api/drawings?board_id&timeframe` | 读取画线 |
| GET | `/api/subplots?board_id&timeframe` | 读取副图 |
| GET | `/api/state?board_id&timeframe` | **完整渲染快照**（全量，前端启动用；费 token，agent 请优先用上面分项） |
| GET | `/api/view` | 用户当前视图窗口 |
| GET | `/api/snapshot?board_id&timeframe` | 读取最新快照（image/png） |
| GET | `/api/config` | 当前配置（只读） |

`start`/`end` 为**毫秒**时间戳，误传秒（<1e11）自动×1000；`/api/kline` 与 `/api/indicators` 范围逻辑一致。

---

## 8. WebSocket（`/ws`）

服务端 → 客户端消息（均含 `board_id` + `timeframe`）：

| type | 说明 |
|------|------|
| `init` | 连接时推送当前画板当前周期完整状态 + boards 列表 |
| `ohlcv_update` | K 线更新（`data`，历史前插时带 `prepended`） |
| `indicator_add` / `indicator_update` | 指标新增 / 同名覆盖（带 `params`/`display_name`/`style`/`lines`） |
| `indicator_refresh` | 指标自动重算完成（带 `params`/`display_name`） |
| `indicator_remove` | 指标删除 |
| `subplot_create` / `subplot_update` / `subplot_remove` | 副图增改删 |
| `board_create` / `board_switch` / `board_remove` | 画板增/切/删 |
| `timeframe_create` / `timeframe_switch` / `timeframe_remove` | 周期增/切/删 |
| `datasource_start` / `datasource_stop` / `datasource_error` | 数据源启/停/错 |
| `markers_update` | 主图标记更新 |

客户端可发 `ping`，服务端回 `pong`（心跳）。

---

## 9. 脚本约定（scripts/）

### 9.1 数据源脚本

```python
def main(params: dict) -> list:
    # 返回 [{timestamp, open, high, low, close, volume}, ...]
    ...
```
- `params` 由 datasource/run-script 传入（如 symbol/timeframe/limit）
- 支持 `params["until"]`（毫秒）：只返回该时间之前的 K 线，用于历史回溯

### 9.2 指标脚本

```python
def main(params: dict, ohlcv: list) -> list | dict:
    # 单线: 返回 [null|number, ...]
    # 多线: 返回 {"lines": [{name, type, values, style, markers?}, ...], "markers": [...]?}
    ...
```
- 通过 `run-script save_as=indicator` 添加的指标会**自动注册为动态指标**：K 线更新时自动重算
- 直接 `POST /api/indicator` 推的是静态指标（不自动重算）

### 9.3 指标脚本元数据（可选，用于自动命名与设置弹窗）

```python
PARAMS = {"period": 20}            # 参数默认值：合并存储，供自动命名+弹窗回显
NAME = "SMA"                        # 可选：显示根名（默认用文件名 stem 大写）
def label(params): return f"SMA({params['period']})"   # 可选：完全自定义显示名
```
- 自动显示名优先级：`run-script display_name` > `label()` > `NAME` > 文件名 stem；再拼参数值，
  超过 3 个参数截断为 `根名(a, b, c, …)`。改参数后显示名自动更新（除非用户自定义）。
- 内部 `name`（indicator_name）稳定不变，`display_name` 仅用于展示，重命名不破坏任何引用。

### 9.4 style 常用字段

`color` / `lineWidth` / `lineStyle`(0实线/1点线/2虚线) / `lineType` / `priceScaleId` /
`fillOpacity` / `topColor` / `bottomColor` / `baseValue`（baseline）。
柱状图（histogram）额外支持 `autoColor`：真=涨跌自动红绿（默认），假=用 `color` 固定单色。
指标默认不显示最后值标记与价格辅助线。

---

## 10. MCP 工具（Streamable HTTP，`/mcp`）

MCP 挂在 **agent 端口**（默认 8766）的 `/mcp`，与 Web 端口共享同一 service 实例，
agent 操作实时推 WS 到浏览器。agent 端口全量鉴权。
连接：`{ "type": "streamable-http", "url": "http://<host>:8766/mcp/", "headers": {...} }`。

| 工具 | 说明 |
|------|------|
| `list_boards` / `create_board` / `delete_board` / `switch_board` | 画板管理 |
| `list_timeframes` / `create_timeframe` / `delete_timeframe` | 周期管理 |
| `set_datasource` | 配置数据源（可轮询） |
| `load_history` | 向左加载历史 |
| `run_script` | 通用脚本执行（save_as: ohlcv/indicator/None）；加指标更推荐用 `add_indicator(script=…)` |
| `overview` | **轻量结构总览**（无数值数组，省token）：探查"图上有什么"首选 |
| `add_indicator` | **加指标统一入口**：`script`=脚本计算 / `values`·`lines`=现成值（两者皆无报错） |
| `delete_indicator` / `update_indicator` | 指标删/改(参数/样式/显示名) |
| `list_scripts` | 列出可用脚本 |
| `create_subplot` / `delete_subplot` | 副图增删 |
| `set_markers` | 主图标记（time 为毫秒，需与 bar 对齐；秒会自动×1000） |
| `take_snapshot` / `get_snapshot` | 截图（触发前端截图/读取最新，含图例+最新价标签） |

划线/取数：`add_drawing` / `update_drawing` / `delete_drawing` / `list_drawings` /
`get_kline` / `get_indicators` / `get_markers` / `list_subplots` / `get_current_view`。
时间单位统一为**毫秒**（ohlcv/划线/markers），仅渲染边界转秒。
截图依赖浏览器连接 `/ws`；合成图含 主图+成交量+副图 拼接及 OHLC/指标图例/最新价标签。

---

## 11. 错误码

| 错误码 | 含义 |
|--------|------|
| `INDICATOR_EXISTS` | replace=false 时同名指标已存在（400） |
| `SCRIPT_NOT_FOUND` | 脚本不存在（500） |
| `SCRIPT_EXEC_ERROR` | 脚本执行异常（500） |
| 404 | 删除/切换不存在的画板/周期/指标/副图 |


---

## 12. 双端口与鉴权

一个进程、共享同一 service，起两个端口（config.yaml `server.web` / `server.agent`
可分别配置 host/port，或被 `AGENTKLINE_WEB_*` / `AGENTKLINE_AGENT_*` 环境变量覆盖）：

| 端口 | 默认 | 面向 | 鉴权 | 内容 |
|------|------|------|------|------|
| web | `0.0.0.0:8765` | 用户浏览器 | **无**（登录预留） | 静态前端、`/ws`、只读、用户交互写（画线增改删、指标设置/删除、画板/周期删除、history、view、snapshot 上传） |
| agent | `127.0.0.1:8766` | AI agent | **全量强制**（读+执行不区分） | `/mcp` 全部工具 + 只读 REST + 执行/管理 REST（run-script、ohlcv、markers、load-csv、指标 push/refresh、副图写、画板/周期创建、datasource、refresh） |

- web 端口**没有**执行/管理类接口（如 `run-script` 在 web 端口 404），从路由层面隔离危险操作。
- agent 端口默认仅本机；如需远程 agent，把 host 改 `0.0.0.0` 并**务必**配置 token。
- token 来源优先级：`AGENTKLINE_TOKEN` > `config.yaml auth.token`。
  配置了 token：agent 端口需 `Authorization: Bearer <token>`，否则 401；
  未配置：agent 端口仅本机可用，远程 403。
- web 端口登录为预留扩展点（`current_web_user`），当前恒匿名；未来实现登录只需改该依赖。

MCP 客户端带 token 示例（注意是 **agent 端口**）：
```json
{ "mcpServers": { "agentkline": {
  "type": "streamable-http",
  "url": "http://<host>:8766/mcp/",
  "headers": { "Authorization": "Bearer <token>" }
} } }
```

> 注意：匿名可划线意味着匿名也可删/涂划线（写操作）。若需匿名只读、写要登录，
> 需把 UI 写接口也移入受保护并给前端注入 token（方案 B）。
