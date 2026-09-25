# AgentKline

**一个可自托管、可脚本化、面向 AI agent 的 K 线交易画板。**

[English →](README.md)

基于 [lightweight-charts](https://github.com/tradingview/lightweight-charts)，FastAPI 后端，
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
- ✏️ **划线与标记** — 水平线 / 趋势线、买卖标记，WS 实时同步到所有客户端
- 📸 **快照** — 服务端合成截图（含 DOM 覆盖层：最新价标签 / OHLC / 图例），agent 可直接读图
- 🎯 **AI 引导呈现** — `switch_board` / `switch_timeframe` / `set_view_range` 让 AI 把用户屏幕带到任意画板/周期/时间段（如回测回撤区间），标记与划线已画好，无需人工翻找
- 🔐 **一标的一板** — 画板建板即锁到 `(源, 标的)` 二元组；换标的/换源=新现场；撞锁返回 `SOURCE_LOCKED` 并附"用此配置新建画板"一键改道
- 🔍 **用户自助搜索流** — 跨 CAPS.symbols 数据源搜索标的，点行=一步建板即锁出图；顶栏固定"＋"按钮发起搜索；板标签右键弹身份证卡
- ⏱ **实时多周期** — 锁定板默认 15m/1h/4h/1d/1w（∩ 源 `INTERVALS`），初始槽全部自动配置；周期行"+"可加任意支持周期，标签恒按短→长排序
- 📚 **内置 Skills** — `skills/` 随仓库发布领域知识（`script-authoring` / `ai-walkthrough`），经 `list_skills` / `load_skill` 按需加载，agent 无需试错即可编写合法脚本
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
`add_drawing` / `set_markers` / `set_view_range` / `list_skills` / `load_skill` /
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
