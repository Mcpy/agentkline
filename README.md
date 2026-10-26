# AgentKline

**A self-hosted, scriptable, agent-ready K-line trading board.**

[中文文档 →](README_zh-CN.md)

Built on [Vela™ by LuxAlgo](https://velacharts.dev) (Apache-2.0), with a FastAPI backend,
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

Since v0.4 the chart is a **scene per symbol** (one symbol, one locked board): the human picks
*what* to watch via the search flow (board created & locked in one click), AI still owns
*how* to analyze — overlays, markers, walkthroughs all anchor to that scene's coordinate system.

## ✨ Features

- 📈 **Multi-board / multi-timeframe** — switch 1d / 4h / 1h within a board, isolated viewports & indicators
- 🧩 **Scriptable indicators** — indicators are server-side Python scripts (`scripts/`), sandbox-executed, saved as overlays or subplots
- 🔌 **Pluggable datasources** — datasources are scripts too (mock, ccxt, …), with optional realtime polling
- ✏️ **Professional drawing tools (native Vela)** — 79 tools in 7 groups (lines/channels/Fibonacci/Gann/patterns/measurements/text) with magnet, measure ruler, eraser, undo, favorites and style templates; drawings live on the board and use `showOn` for cross-timeframe visibility, synced over WebSocket
- 📸 **Snapshot** — server-composed chart screenshot (`renderer.screenshot()`: panes/canvas overlays incl. out-of-range price pin; host DOM such as the OHLC strip is not composited) that agents can read directly
- 🎯 **AI-guided walkthrough** — `switch_board` / `switch_timeframe` / `set_view_range` let the AI bring the user's screen to any board, timeframe and time window (e.g. a backtest drawdown), with its markers & drawings already on it — no manual hunting
- 🔐 **One symbol, one scene** — boards lock to `(source, symbol)` at creation; switching symbol/source means a new scene; collisions return `SOURCE_LOCKED` with a one-click "create board with this config" suggestion
- 🔍 **User self-service search flow** — search symbols across CAPS-enabled datasources, click a row = board created & locked & charted in one step; a fixed "＋" button in the toolbar starts it; right-click a board tab for its ID card
- ⚡ **Request budget** — visibility-tiered polling (visible slot fast, others 60/120/300s + refetch-on-switch), per-source batched tickers, visible-row quote dedup: ~80% fewer exchange calls
- 🇨🇳 **A-share built-in source** — `ashare_free`: realtime quotes + full-interval K-lines + adjust factor; multi-vendor fallback chain (Eastmoney primary, Tencent/Sina backup)
- 📈 **Full indicator library (v0.5.3–0.5.4)** — all 74 Vela built-in studies ported to the Python single-source engine (plus KDJ); searchable, category-filtered grid with repeatable instances and schema-driven parameter forms; user/agent scripts in `scripts/indicator/` appear in a dedicated **Custom** bucket
- ⭐ **Favorites / recently used (v0.5.4)** — star studies in the library and jump back via a recency list (last 8 adds); local-only localStorage, survives reloads without touching server state
- 📊 **VPVR visible-range volume profile (v0.5.4–0.6.0)** — Vela native layer toggled by a fixed-width `VPVR` chip aligned with the OHLC row; native legend row hidden, switch persisted per board (0.6.0 removed the settings gear — toggle only, same as Vol)
- 🏷 **Out-of-range last price pin (v0.5.4)** — when the latest price leaves the visible price range, an `▲/▼` price block stays at the top/bottom of the axis; in range the native label is untouched
- 🧾 **Results as first-class board citizens (v0.6.0)** — imported/backtested results live on the same board as the chart: result bar with chips, 15-metric overview, equity sub-pane, buy/sell marks and a comparison table; no separate report page
- 🔍 **Trade details & return curves (v0.6.0)** — paginated per-trade list (entry/exit, holding time, PnL, reasons, explicit units), page summary, single-trade card with “Locate on chart”, and three chart tabs: time-based return curve, per-trade cumulative %, monthly PnL
- 🧮 **Backtest from the chart (v0.6.1)** — `+Backtest` in the result bar: engine, strategy, direction, optional time range (start/end/bars linked, up to 20k bars with automatic history fetch), cash/fees/slippage and stop-loss/take-profit; results land as frozen result instances with equity, trades and buy/sell marks
- 🧩 **Engine plugins (v0.6.1)** — built-in signal engine plus a zero-dependency `agentkline-engine-core`; every engine (including builtin) runs as an isolated `ak-engine` subprocess, third-party engines register via entry points and depend only on the core framework
- 🔬 **Result review, upgraded (v0.6.2)** — click a trade box or a B/S mark on the chart to open that trade (entry/exit reasons included); boxes show holding time and P&L slope, the selected one is outlined and the rest fade, and the underwater fill between equity and its high-water mark shows drawdown depth and recovery; dragging never clears the selection
- 📤 **Compare & export (v0.6.2)** — up to five results normalized to 100 with a baseline line; the comparison table highlights best return / drawdown / Sharpe, and the full trade list exports to CSV (UTF-8 BOM, opens cleanly in Excel)
- 💾 **State on disk (v0.6.3)** — boards, indicator instances, drawings, results and the watchlist persist to a local SQLite store (WAL; `~/.agentkline` by default, override with `AGENTKLINE_DATA_DIR`); after a restart the workspace is back, while bars are refetched from the source and indicators are recomputed
- 🧹 **Bounded result history (v0.6.3)** — each board keeps the latest 100 results and auto-evicts the oldest beyond that (equity and trades included); a permanent hint in the result bar turns into a warning near the limit, and an evicted result is announced with a toast — no unbounded database, no silent loss
- 🎨 **Native-faithful indicator visuals** — every ported study starts from Vela's own palette, line kinds, fills, levels and zones (BOLL bands/basis, SAR dots, MACD 4-state momentum columns, RSI ramp + zones, Supertrend steps…); the settings dialog edits color/width/line style/band fill/ink slots with immediate repaint
- 🗂 **Radar groups** — themed watch groups (collapse/rename/drag-move, delete falls rows back to default)
- 📡 **Radar watchlist** — pin symbols across boards (CAPS.ticker sources); live price/change with three-state dispatch (visible heartbeat / hidden unread badge / watch-only); row click = jump to scene or one-step lock-create
- ⏱ **Realtime multi-timeframe** — locked boards default to 15m/1h/4h/1d/1w (∩ source `INTERVALS`), all slots auto-configured; the "+" on the timeframe row adds any supported interval, tabs keep short→long order
- 📚 **Bundled skills** — on-demand domain knowledge shipped in `skills/` (`datasource-authoring`, `indicator-authoring`, `strategy-authoring`, `ai-walkthrough`), loaded via `list_skills` / `load_skill` so any agent can author legal scripts and run backtests without trial-and-error
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
`draw_drawing` / `draw_many` / `list_drawing_tools` / `set_markers` / `set_view_range` / `list_skills` / `load_skill` /
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

## Chart Engine Attribution

Charts rendered by [Vela™](https://velacharts.dev) (LuxAlgo, Apache-2.0 License).
Vela is a dependency reference (not a fork); see `frontend/vendor/assets/vela.global.min.js.sha256` for the pinned bundle checksum.
图表渲染由 Vela™（LuxAlgo，Apache-2.0）承担；依赖引用非 fork，bundle 校验和见 frontend/vendor/assets/vela.global.min.js.sha256。
