# AgentKline

**一个可自托管、可脚本化、面向 AI agent 的 K 线交易画板。**

[English →](README.md)

基于 [Vela™ by LuxAlgo](https://velacharts.dev)（Apache-2.0），FastAPI 后端，
服务端 **Python 可脚本化指标**，并通过 **MCP** 为 AI agent 提供一等接入。

> AgentKline 是一个可自托管的交互式 K 线画板：多画板 / 多周期、可插拔数据源、
> 服务端 Python 指标脚本、划线与标记，并为 AI agent 提供完整的 REST + MCP 控制面。

---

## 🎯 设计理念：AI 优先的可视化面板

AgentKline 不是给人"点来点去"的图表工具，而是让 **AI 全权掌控图表**：

- **数据由 AI 提供** — 数据源即脚本，AI 可接入任意行情（交易所、CSV、自建数据）
- **指标由 AI 编写** — 自定义指标就是 Python 脚本，随写随用
- **分析由 AI 完成** — 画线、支撑/压力、买卖标记，AI 直接落到图上
- **人只负责看和决策** — 面板把 AI 的思考过程可视化，服务于用户的最终判断

简言之：给 AI 量化一块**自由度极高**的画布——把"操作图表"交给 AI，把"看懂并决策"留给人。

v0.4 起图表是**一标的一板的现场**：人通过搜索流决定*看什么*（一步建板即锁），
AI 仍然垄断*怎么分析*——叠加、标记、引导呈现都锚定该现场的坐标系。

## ✨ 特性

- 📈 **多画板 / 多周期** — 同一画板内 1d / 4h / 1h 自由切换，独立视口与指标
- 🧩 **可脚本化指标** — 指标是服务端 Python 脚本（`scripts/`），沙箱执行，可存为主图叠加或副图
- 🔌 **可插拔数据源** — 数据源同样是脚本（内置 mock、ccxt 等），可轮询实时刷新
- ✏️ **专业画线（Vela 原生）** — 79 种工具分 7 组（趋势/通道/斐波那契/Gann/形态/测量/文字），磁吸、测量尺、橡皮、撤销、收藏与样式模板齐全；画线属板、`showOn` 控跨周期，WS 实时同步
- 📸 **快照** — 服务端 `renderer.screenshot()` 图表截图（画布/pane/越界贴边标签；OHLC 条带等宿主 DOM 不参与合成），agent 可直接读图
- 🎯 **AI 引导呈现** — `switch_board` / `switch_timeframe` / `set_view_range` 让 AI 把用户屏幕带到任意画板/周期/时间段（如回测回撤区间），标记与划线已画好，无需人工翻找
- 🔐 **一标的一板** — 画板建板即锁到 `(源, 标的)` 二元组；换标的/换源=新现场；撞锁返回 `SOURCE_LOCKED` 并附"用此配置新建画板"一键改道
- 🔍 **用户自助搜索流** — 跨 CAPS.symbols 数据源搜索标的，点行=一步建板即锁出图；顶栏固定"＋"按钮发起搜索；板标签右键弹身份证卡
- ⚡ **请求预算** — 可见性分级轮询（可见槽快频/其余 60/120/300s + 切即补拉）、按源批量 tickers、可见行 quote 去重：交易所调用 ↓~80%
- 🇺 **美股内置源** — `usstock_free`：Yahoo K线（单厂商，免费美股K线业界稀缺）+ 实时互备（spark→腾讯qt）+ wiki 种子宇宙索引（S&P500+Nasdaq100）；
- 🌐 **前端多语言（zh/en，语言包插件化、构建期自动发现）**
- 🪙 **币安现货+永续双市场** — `BTC/USDT`=现货、`BTC/USDT:USDT`=永续；含 TradFi 永续 205（美股/港股/韩股/AI 独角兽/商品）+ 股票代币现货 78
- 🇨🇳 **A 股内置源** — `ashare_free`：实时报价 + 全周期 K 线 + 复权；多厂商回落链（东财主、腾讯/新浪备）
- 📈 **完整指标库（v0.5.3–0.5.4）** — Vela 74 个内置经典研究全量移植到 Python 单源引擎（另加 KDJ）；搜索 + 分类 + 多列网格，支持重复添加实例与 schema 驱动参数表单；用户/agent 写入 `scripts/indicator/` 的脚本自动进「自定义」分类
- ⭐ **指标库收藏 / 最近使用（v0.5.4）** — 卡片星标收藏、最近使用按添加倒序（上限 8）；纯前端 localStorage，刷新保留，不影响服务端状态
- 📊 **VPVR 可见区间成交量分布（v0.5.4–0.6.0）** — Vela 原生 layer；与 OHLC 同行的固定宽度 `VPVR` chip 开关；原生图例行隐藏，开关按板持久化（0.6.0 移除设置齿轮，与 Vol 一样只有开关）
- 🏷 **越界最新价贴边（v0.5.4）** — 最新价超出可见价格区间时，价格轴顶部/底部保留 `▲/▼` 价格块；区间内仍走原生标签，不重复
- 🧾 **结果成为画板一等公民（v0.6.0）** — 回测/导入的结果与 K 线同现场：结果栏 chip、15 项概览、净值副图、B/S 交易点与对照表，不另开报表页
- 🔍 **交易详情与收益曲线（v0.6.0）** — 逐笔列表分页（开平仓、持仓时长、盈亏、原因、明确单位）、本页小结、单笔卡与「在图上定位」；三个图选项卡：按时间的收益曲线、按笔序号的累计盈亏 %、月度盈亏
- 🧮 **图上一键回测（v0.6.1）** — 结果栏「+回测」：引擎/策略/方向/可选时间范围（开始、结束、根数三者联动，最多 2 万根，历史自动补）/资金/费率/滑点/止损止盈；跑完冻结为结果实例，带净值、交易与 B/S 点
- 🧩 **引擎插件化（v0.6.1）** — 内置 signal 引擎 + 零依赖 `agentkline-engine-core`；所有引擎（含 builtin）都跑在独立 `ak-engine` 子进程里，第三方引擎按 entry point 注册、只依赖 core
- 🔬 **结果复盘增强（v0.6.2）** — 图上点交易盒或 B/S 标记直接打开该笔（含进出场原因）；盒子宽=持仓时长、斜率=盈亏方向，选中描边、其余淡出；净值与高水位之间的水下填充显示回撤深度与修复过程；拖拽平移不会误清选中
- 📤 **对照与导出（v0.6.2）** — 最多 5 条结果归一到 100 并带基准线；对照表高亮最优收益/回撤/夏普；全部交易一键导出 CSV（UTF-8 BOM，Excel 直接打开）
- 💾 **现场落盘（v0.6.3）** — 画板、指标实例、画线、结果与雷达写进本地 SQLite（WAL；默认 `~/.agentkline`，`AGENTKLINE_DATA_DIR` 可改）；重启后现场原样回来，K 线按来源重取、指标自动重算
- 🧹 **结果保留有数（v0.6.3）** — 每板保留最近 100 条结果，超出自动删除最旧一条（含净值与交易）；结果栏常驻提示、接近上限转警示、被删时 toast 明示——库不会无限增长，也不会静默丢数据
- 🎨 **指标视觉保真** — 每个移植研究都从 Vela 原生配色/线型/填充带/水平线/区带起步（BOLL 带+中轨、SAR 圆点、MACD 动能四态柱、RSI 渐变+三区、SuperTrend 阶梯…）；设置面板可改颜色/粗细/线型/填充带/涨跌双色，改完即时生效
- 🗂 **雷达分组** — 主题分组（折叠/重命名/拖拽移组，删组行回落默认组）
- 📡 **雷达盯盘** — 跨板盯符号（CAPS.ticker 源）：实时价/涨跌幅 + 三态分发（visible 心跳/hidden 未读角标/watch 仅面板）；行点击=切现场或一步建板即锁
- ⏱ **实时多周期** — 锁定板默认 15m/1h/4h/1d/1w（∩ 源 `INTERVALS`），初始槽全部自动配置；周期行"+"可加任意支持周期，标签恒按短→长排序
- 📚 **内置 Skills** — `skills/` 随仓库发布领域知识（`datasource-authoring` / `indicator-authoring` / `strategy-authoring` / `ai-walkthrough`），经 `list_skills` / `load_skill` 按需加载，agent 无需试错即可写脚本、跑回测
- 🤖 **Agent 原生** — 双端口架构 + 标准 MCP（Streamable HTTP），AI 可读、可写、可执行

## 🏗 架构：双端口

| 端口 | 面向 | 鉴权 | 内容 |
|---|---|---|---|
| `8765` (web) | 用户浏览器 | 无（登录预留） | 静态前端、WebSocket、用户级读写 |
| `8766` (agent) | AI agent | **全量 Bearer token** | 完整 REST + `/mcp`（含执行类） |

两个端口共享同一进程内的 service 与 WS 连接注册表，agent 的改动会实时推送到浏览器。

## 🚀 快速开始

```bash
pip install -e .
# 构建前端（首次必须）
cd frontend && npm install && npm run build && cd ..
# 启动（双端口）
./start.sh            # 或: python -m agentkline.api.app
```

- 用户界面: http://localhost:8765
- Agent MCP: http://localhost:8766/mcp/ （需 Bearer token）

## 🤖 MCP 接入

```json
{
  "mcpServers": {
    "agentkline": {
      "url": "http://<host>:8766/mcp/",
      "headers": { "Authorization": "Bearer <your-token>" }
    }
  }
}
```

常用工具：`overview` / `get_kline` / `get_indicators` / `add_indicator` / `run_script` /
`draw_drawing` / `draw_many` / `list_drawing_tools` / `set_markers` / `set_view_range` / `list_skills` / `load_skill` /
`take_snapshot`（返回标准 image 块，多模态模型可直接读图）。

健壮性：越界标记时间会被丢弃并在 `dropped` 数组回报（不静默）；指标 `NaN`/`Inf`
清洗为 `null`，保证浏览器 JSON 合法。

读取接口按省 token 拆分：`overview`（仅结构）/ `get_kline`（K线+成交量）/
`get_indicators`（指标值，可过滤）/ `get_markers` / `list_drawings`。

## ⚙️ 配置

见 `config.example.yaml`。要点：

- `server.web` / `server.agent` 的 host/port，可被环境变量覆盖：
  `AGENTKLINE_WEB_HOST` / `AGENTKLINE_WEB_PORT` / `AGENTKLINE_AGENT_HOST` / `AGENTKLINE_AGENT_PORT`
- `auth.token`：agent 端口 Bearer token，环境变量 `AGENTKLINE_TOKEN` 优先级更高
- `scripts.dir` / `scripts.sandbox_level`：指标与数据源脚本目录及沙箱级别

## 📚 文档

- `docs/API文档.md` — REST / WS / MCP 全量接口
- `docs/开发文档.md` — 模块结构、构建与部署
- `docs/脚本编写指南.md` / `skills/script-authoring.md` — 如何编写合法的指标/数据源脚本

## License

Apache-2.0
