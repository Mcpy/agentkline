# 附录 A：REST 路由表（自动生成，勿手改）

| 方法 | 路径 | 摘要 |
|---|---|---|
| POST | `/api/board` | Create Board |
| POST | `/api/board/empty` | Create Empty Board |
| GET | `/api/board/{board_id}` | Switch Board |
| PUT | `/api/board/{board_id}` | Update Board |
| DELETE | `/api/board/{board_id}` | Delete Board |
| GET | `/api/board/{board_id}/interval_options` | Interval Options |
| POST | `/api/board/{board_id}/timeframe` | Create Timeframe |
| GET | `/api/board/{board_id}/timeframe/{tf}` | Switch Timeframe |
| DELETE | `/api/board/{board_id}/timeframe/{tf}` | Delete Timeframe |
| POST | `/api/board/{board_id}/timeframe/{tf}/backfill` | Backfill |
| PUT | `/api/board/{board_id}/timeframe/{tf}/kline_source` | Set Kline Source |
| GET | `/api/board/{board_id}/timeframe/{tf}/kline_source` | Get Kline Source |
| POST | `/api/board/{board_id}/timeframe/{tf}/refresh` | Refresh Timeframe |
| GET | `/api/board/{board_id}/timeframes` | List Timeframes |
| GET | `/api/boards` | List Boards |
| GET | `/api/config` | Get Config |
| POST | `/api/drawing` | Add Drawing |
| POST | `/api/drawing/{drawing_id}` | Update Drawing |
| DELETE | `/api/drawing/{drawing_id}` | Delete Drawing |
| GET | `/api/drawings` | List Drawings |
| POST | `/api/indicator` | Push Indicator |
| POST | `/api/indicator/refresh/{inst_id}` | Refresh Indicator |
| DELETE | `/api/indicator/{inst_id}` | Delete Indicator |
| PUT | `/api/indicator/{inst_id}` | Update Indicator |
| GET | `/api/indicators` | Get Indicators |
| GET | `/api/kline` | Get Kline |
| GET | `/api/markers` | Get Markers |
| POST | `/api/markers` | Push Markers |
| GET | `/api/overview` | Get Overview |
| POST | `/api/run-script` | Run Script |
| GET | `/api/scripts` | List Scripts |
| POST | `/api/scripts` | Save Script |
| GET | `/api/search` | Search Symbols |
| GET | `/api/skills` | List Skills |
| GET | `/api/skills/{name}` | Load Skill |
| GET | `/api/snapshot` | Get Snapshot |
| POST | `/api/snapshot` | Push Snapshot |
| GET | `/api/state` | Get State |
| POST | `/api/subplot` | Create Subplot |
| PUT | `/api/subplot/{name}` | Update Subplot |
| DELETE | `/api/subplot/{name}` | Delete Subplot |
| GET | `/api/subplots` | List Subplots |
| GET | `/api/view` | Get View |
| POST | `/api/view` | Report View |
| POST | `/api/view/range` | Set View Range |

# 附录 B：MCP 工具表（自动生成，勿手改）

| 工具 | 说明首行 |
|---|---|
| `list_boards` | 列出所有画板 |
| `create_board` | 创建画板。intervals 为初始周期列表（如 ["1d","4h"]），首个为默认周期。 |
| `delete_board` | 删除画板（连同其所有周期、K线、指标、副图与画线，不可恢复）。 |
| `switch_board` | 切换当前画板，前端随之显示该画板（广播其默认周期状态）；用于 AI 主动展示。 |
| `list_timeframes` | 列出画板的时间周期 |
| `create_timeframe` | 给画板添加时间周期（如 1d/4h/1h）。已锁定在线板：新周期槽由系统自动注入 |
| `delete_timeframe` | 删除时间周期（连同其K线/指标/画线）。若删的是当前周期，自动回退到默认周期。 |
| `switch_timeframe` | 切换当前时间周期，前端随之显示该周期（广播该周期状态）；用于 AI 主动展示，类比 switch_board。 |
| `set_kline_source` | 声明式配置 K 线来源（幂等，PUT 语义）。script 为 id（kind/name，如 datasource/ccxt_binance）。 |
| `backfill` | 向左补充更早的历史K线（前插到现有最早一根之前）。 |
| `run_script` | 执行脚本并返回结果（窄身：图上不留痕，save_as 已废除）。 |
| `overview` | 轻量结构总览：品种/周期/数据源/指标元信息/副图名/画线与标记计数等， |
| `get_current_view` | 获取用户当前视图（画板/周期/可见时间窗口），由前端上报 |
| `set_view_range` | 让前端聚焦到指定时间窗口（AI 主动把画面拉到某段时间，如回测亏损区间）。 |
| `add_indicator` | 加指标（统一入口，inst_id 把手）。 |
| `delete_indicator` | 按 inst_id 删除指标实例（登记处+各周期物化一次删净；现有 inst_id 见 overview）。 |
| `update_indicator` | 更新指标实例（inst_id 把手）。params=新参数(重声明配方触发重算)；style=整体样式； |
| `list_scripts` | 列出全部脚本（双根：builtin 内置只读 / custom 可写）。 |
| `search_symbols` | 标的搜索（P1）：返回 rows=[{symbol, source, display, has_board}]，行=完整二元组(源,裸符号)； |
| `save_script` | 保存自定义脚本到 custom 根（保存即校验：main 存在/CAPS 一致性/字面元数据合法）。 |
| `create_subplot` | 创建副图——主图下方的独立小面板，用于放置指标（如 MACD/KDJ/成交量）。 |
| `delete_subplot` | 删除副图（连同其上指标） |
| `set_markers` | 在K线主图设置标记（覆盖式，替换该周期已有全部标记；读取用 get_markers）。 |
| `add_drawing` | 画线。type: hline(水平,points=[{price}]) / trend(趋势,points=[{time,price},{time,price}])。 |
| `delete_drawing` | 删除划线 |
| `update_drawing` | 更新划线：visible(显隐)/color/line_width/line_style(solid|dashed|dotted)/text |
| `list_drawings` | 列出画板+周期的所有划线 |
| `list_subplots` | 列出画板+周期的所有副图 |
| `get_kline` | 获取区间K线（含成交量）。不传start/end=用户当前view窗口。 |
| `get_indicators` | 获取区间指标值，范围逻辑同 get_kline（不传=当前view）。 |
| `get_markers` | 读取主图标记（买卖点等）。返回标记数组，字段同 set_markers（time/position/color/shape/text）； |
| `take_snapshot` | 触发前端截图并返回图片+路径。需有浏览器连着 /ws。 |
| `get_snapshot` | 读取最新快照（图片+路径）。快照由浏览器截图上传产生。 |
| `list_skills` | 列出可用 skills（name+description）。先用它发现，再用 load_skill 读全文。 |
| `load_skill` | 加载指定 skill 的完整文档（如 script-authoring / ai-walkthrough）。 |
