# AgentKline

**A self-hosted, scriptable, agent-ready K-line trading board.**

[中文文档 →](README_zh-CN.md)

Built on [lightweight-charts](https://github.com/tradingview/lightweight-charts), with a FastAPI backend,
server-side **Python-scriptable indicators**, and first-class **AI-agent access via MCP**.

---

## 🎯 Philosophy: an AI-driven visualization panel

AgentKline is not a click-around charting tool for humans — it is designed so that **AI fully controls the chart**:

- **Data supplied by AI** — datasources are scripts; AI can plug in any market feed (exchange, CSV, custom)
- **Indicators authored by AI** — custom indicators are plain Python scripts, written and applied on the fly
- **Analysis performed by AI** — trendlines, support/resistance and buy-sell markers are drawn straight onto the chart
- **Humans only watch & decide** — the panel visualizes the AI's reasoning, serving the user's final judgment

In short: a **high-freedom canvas for AI quant** — "operating the chart" is delegated to AI,
while "understanding & deciding" stays with the human.

## ✨ Features

- 📈 **Multi-board / multi-timeframe** — switch 1d / 4h / 1h within a board, isolated viewports & indicators
- 🧩 **Scriptable indicators** — indicators are server-side Python scripts (`scripts/`), sandbox-executed, saved as overlays or subplots
- 🔌 **Pluggable datasources** — datasources are scripts too (mock, ccxt, …), with optional realtime polling
- ✏️ **Drawings & markers** — hline / trendline, buy-sell markers, synced to all clients over WebSocket
- 📸 **Snapshot** — server-composed screenshots (incl. DOM overlays: last-price label / OHLC / legends) that agents can read directly
- 🎯 **AI-guided walkthrough** — `switch_board` / `switch_timeframe` / `set_view_range` let the AI bring the user's screen to any board, timeframe and time window (e.g. a backtest drawdown), with its markers & drawings already on it — no manual hunting
- 📚 **Bundled skills** — on-demand domain knowledge shipped in `skills/` (`script-authoring`, `ai-walkthrough`), loaded via `list_skills` / `load_skill` so any agent can author legal scripts without trial-and-error
- 🤖 **Agent-native** — dual-port architecture + standard MCP (Streamable HTTP): AI can read, write and execute

## 🏗 Architecture: dual-port

| Port | Audience | Auth | Serves |
|---|---|---|---|
| `8765` (web) | user browsers | none (login hook reserved) | static frontend, WebSocket, user-level read/write |
| `8766` (agent) | AI agents | **full Bearer token** | complete REST + `/mcp` (incl. exec) |

Both ports share the same in-process service and WS registry, so agent changes push to browsers in realtime.

## 🚀 Quick start

```bash
pip install -e .
# build the frontend (required once)
cd frontend && npm install && npm run build && cd ..
# start (dual-port)
./start.sh            # or: python -m agentkline.api.app
```

- Web UI: http://localhost:8765
- Agent MCP: http://localhost:8766/mcp/ (Bearer token required)

## 🤖 MCP integration

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

Common tools: `overview` / `get_kline` / `get_indicators` / `add_indicator` / `run_script` /
`add_drawing` / `set_markers` / `set_view_range` / `list_skills` / `load_skill` /
`take_snapshot` (returns a standard image block — multimodal models can read the chart directly).

Robustness: out-of-range marker times are dropped and reported in a `dropped` array (never silent);
indicator `NaN`/`Inf` are sanitized to `null` so JSON stays valid for the browser.

Read APIs are split for token efficiency: `overview` (structure only) / `get_kline` (candles+volume) /
`get_indicators` (values, filterable) / `get_markers` / `list_drawings`.

## ⚙️ Configuration

See `config.example.yaml`. Highlights:

- `server.web` / `server.agent` host & port, overridable by env:
  `AGENTKLINE_WEB_HOST` / `AGENTKLINE_WEB_PORT` / `AGENTKLINE_AGENT_HOST` / `AGENTKLINE_AGENT_PORT`
- `auth.token`: Bearer token for the agent port; env `AGENTKLINE_TOKEN` takes precedence
- `scripts.dir` / `scripts.sandbox_level`: indicator & datasource script dir and sandbox level

## 📚 Docs

- `docs/API文档.md` — full REST / WS / MCP reference
- `docs/开发文档.md` — module layout, build & deployment
- `docs/脚本编写指南.md` / `skills/script-authoring.md` — how to write legal indicator & datasource scripts

## License

Apache-2.0
