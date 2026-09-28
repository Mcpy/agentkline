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
| GET | `/api/board/{board_id}/timeframe/{timeframe}` | Switch Timeframe |
| DELETE | `/api/board/{board_id}/timeframe/{timeframe}` | Delete Timeframe |
| POST | `/api/board/{board_id}/timeframe/{timeframe}/backfill` | Backfill |
| GET | `/api/board/{board_id}/timeframe/{timeframe}/kline_source` | Get Kline Source |
| PUT | `/api/board/{board_id}/timeframe/{timeframe}/kline_source` | Set Kline Source |
| POST | `/api/board/{board_id}/timeframe/{timeframe}/refresh` | Refresh Timeframe |
| GET | `/api/board/{board_id}/timeframes` | List Timeframes |
| GET | `/api/boards` | List Boards |
| GET | `/api/config` | Get Config |
| POST | `/api/drawing` | Add Drawing |
| POST | `/api/drawing/{drawing_id}` | Update Drawing |
| DELETE | `/api/drawing/{drawing_id}` | Delete Drawing |
| GET | `/api/drawings` | List Drawings |
| POST | `/api/indicator` | Add Indicator |
| POST | `/api/indicator/refresh/{inst_id}` | Refresh Indicator |
| PUT | `/api/indicator/{inst_id}` | Update Indicator |
| DELETE | `/api/indicator/{inst_id}` | Delete Indicator |
| GET | `/api/indicators` | Get Indicators |
| GET | `/api/kline` | Get Kline |
| GET | `/api/markers` | Get Markers |
| POST | `/api/markers` | Set Markers |
| GET | `/api/overview` | Overview |
| GET | `/api/quotes` | Get Quotes |
| POST | `/api/run-script` | Run Script |
| GET | `/api/scripts` | List Scripts |
| POST | `/api/scripts` | Save Script |
| GET | `/api/search` | Search Symbols |
| GET | `/api/skills` | List Skills |
| GET | `/api/skills/{name}` | Load Skill |
| GET | `/api/snapshot` | Get Snapshot File |
| POST | `/api/snapshot` | Push Snapshot |
| GET | `/api/state` | Get State |
| POST | `/api/subplot` | Create Subplot |
| PUT | `/api/subplot/{name}` | Update Subplot |
| DELETE | `/api/subplot/{name}` | Delete Subplot |
| GET | `/api/subplots` | List Subplots |
| GET | `/api/view` | Get Current View |
| POST | `/api/view` | Report View |
| POST | `/api/view/range` | Set View Range |
| GET | `/api/watchlist` | Watchlist List |
| POST | `/api/watchlist/groups` | Watchlist Group Add |
| DELETE | `/api/watchlist/groups` | Watchlist Group Remove |
| PUT | `/api/watchlist/groups/rename` | Watchlist Group Rename |
| PUT | `/api/watchlist/move` | Watchlist Move |
| POST | `/api/watchlist/rows` | Watchlist Add |
| DELETE | `/api/watchlist/rows` | Watchlist Remove |

# 附录 B：MCP 工具表（自动生成，勿手改）

| 工具 | 说明首行 |
|---|---|
| `list_boards` | 列出所有画板 |
| `list_skills` | 列出可用 skills（name+description）。先用它发现，再用 load_skill 读全文。 |
| `load_skill` | 加载指定 skill 的完整文档（如 datasource-authoring / indicator-authoring / ai-walkthrough）。 |
| `search_symbols` | 搜索可交易标的。返回候选行，每行=一个"来源+符号"组合（has_board=True 表示该组合已有画板）。 |
| `switch_board` | 切换当前画板，前端随之显示该画板（广播其默认周期状态）；用于 AI 主动展示。 |
| `list_timeframes` | 列出画板的时间周期 |
| `switch_timeframe` | 切换当前时间周期，前端随之显示该周期（广播该周期状态）；用于 AI 主动展示，类比 switch_board。 |
| `get_kline` | 获取区间K线（含成交量）。不传start/end=用户当前view窗口。 |
| `get_indicators` | 获取区间指标值，范围逻辑同 get_kline（不传=当前view）。 |
| `get_markers` | 读取主图标记（买卖点等）。返回标记数组，字段同 set_markers（time/position/color/shape/text）； |
| `overview` | 轻量结构总览：品种/周期/数据源/指标元信息/副图名/画线与标记计数等， |
| `list_subplots` | 列出画板+周期的所有副图 |
| `list_drawings` | 列出画板+周期的所有划线 |
| `get_current_view` | 获取用户当前视图（画板/周期/可见时间窗口），由前端上报 |
| `create_board` | 新建一个图表画板。两种用法： |
| `add_drawing` | 画线。type: hline(水平,points=[{price}]) / trend(趋势,points=[{time,price},{time,price}])。 |
| `update_drawing` | 更新划线：visible(显隐)/color/line_width/line_style(solid|dashed|dotted)/text |
| `delete_drawing` | 删除划线 |
| `backfill` | 向左补拉更早的历史 K 线（看更久远的行情用）。前提：该板数据源支持历史回补（list_scripts 里 caps 含 backfill；csv 类源不支持，返回 prepended=0）。返回本次补拉根数与当前总根数。 |
| `set_markers` | 在K线主图设置标记（覆盖式，替换该周期已有全部标记；读取用 get_markers）。 |
| `create_timeframe` | 给画板加一个时间周期（如 '4h'）。实时板的新周期会自动取数出图；加完用 switch_timeframe 切过去看。 |
| `delete_indicator` | 把一个指标从图上移除（inst_id 从 overview 的 indicators 列表拿），一次删净不留残影。改参数请用 update_indicator，别删了重加。 |
| `update_indicator` | 改一个已加指标（inst_id 从 overview 的 indicators 列表拿）。 |
| `delete_board` | 删除画板（连同其所有周期、K线、指标、副图与画线，不可恢复）。 |
| `delete_timeframe` | 删除时间周期（连同其K线/指标/画线）。若删的是当前周期，自动回退到默认周期。 |
| `list_scripts` | 列出全部可用脚本（内置+自定义）。每条含：id（引用格式如 'indicator/macd'，加指标/配源都用它）、 |
| `save_script` | 保存自定义脚本到 custom 根（保存即校验：入口函数存在/能力声明一致/元数据合法）。 |
| `set_view_range` | 让前端聚焦到指定时间窗口（AI 主动把画面拉到某段时间，如回测亏损区间）。 |
| `run_script` | 跑一次脚本拿计算结果（**不上图、不留痕**）。适合：试算指标输出、拉一段数据源样本检查。要让指标上图用 add_indicator；要当画板数据源用 set_kline_source。 |
| `add_indicator` | 加一个指标到图上。最常用：加内置指标，如 script='indicator/macd'（内置清单见 list_skills 之外的 list_scripts）。 |
| `set_kline_source` | 给"画板+周期"配置或更换 K 线数据来源。 |
| `create_subplot` | 创建副图——主图下方的独立小面板，用于放置指标（如 MACD/KDJ/成交量）。 |
| `delete_subplot` | 删除副图（连同其上指标） |
| `watchlist_list` | 读雷达盯盘面板：groups[]→rows[]，每行=一个盯盘标的，含最新价/涨跌幅/显隐状态/是否有对应画板在现场。加盯用 watchlist_add，移组用 watchlist_move，建组用 watchlist_group_add。 |
| `watchlist_add` | 加入雷达盯盘（幂等）。源须声明 CAPS.ticker，违则 TICKER_UNSUPPORTED；group_id 可选（默认组 default） |
| `watchlist_remove` | 移出雷达盯盘 |
| `watchlist_group_add` | 雷达新建分组（重名 GROUP_EXISTS） |
| `watchlist_group_rename` | 雷达分组改名（默认组 GROUP_PROTECTED） |
| `watchlist_group_remove` | 删除雷达分组，**组内盯盘行一并级联删除**（行不保留，组删行没）；默认组不可删（GROUP_PROTECTED）。只想移走行请先用 watchlist_move。 |
| `watchlist_move` | 雷达行移组+定位（index=None 追加组尾；拖拽落定调用） |
| `get_quotes` | 全行 quotes 快照（AI 读盘用）；面板实时走 WS quotes_update |
| `take_snapshot` | 触发前端截图并返回图片+路径。需有浏览器连着 /ws。 |
| `get_snapshot` | 读取最新快照（图片+路径）。快照由浏览器截图上传产生。 |
