# BTC 交互式画板 — 需求说明书（PRD）

> **版本**：v1.0（已确认）
> **日期**：2026-08-11
> **作者**：小幺（基于哥哥需求草拟）
> **目标读者**：小一 / 小c / 任何接手的开发者

---

## 一、项目背景

量化交易团队当前正在开发自定义技术指标，需要一个**可视化的调试工具**，能快速验证 Python 指标的正确性。

当前痛点：

1. **指标调试效率低**：每次调整指标参数都要重写 HTML 文件
2. **缺少统一的图表环境**：不同开发者用不同工具看图表，无法对齐判断
3. **数据源分散**：历史数据、Python 指标计算结果无法在同一界面融合

> **备注**：实时行情模式在 v0.1 中**暂不实现**，作为 v0.2 规划（见附录 D）。

---

## 二、产品目标

构建一个**单页面、多画板**的 BTC 图表应用，**v0.1 重点是画板 + 数据源 + 指标调试**：

| 概念 | 用途 | 数据来源 | 状态 |
|------|------|----------|------|
| **画板** | 多画板横向对比 + 多时间周期同列 | 任意（脚本统一）| ✅ v0.1 |
| **数据源** | K 线数据获取（静态/实时）| Python 脚本 | ✅ v0.1 |
| **指标** | 技术指标计算（自动重算）| Python 脚本 | ✅ v0.1 |

**v0.4 架构重构**：实时模式**并入数据源**概念，不再是独立模式

**核心原则**：用户打开一次网页，**所有更新通过 API 推送，页面不刷新**

---

## 三、核心功能需求（v0.1）

### 3.1 模式切换

#### 需求 MO-1：模式 Tab 切换
- 页面顶部有一个**模式切换 Tab**
- v0.1 只有一个 Tab：**画板模式**（未来 v0.2 加"实时行情模式"）
- Tab 状态保存在 localStorage（刷新页面后保持）

---

### 3.2 画板模式

#### 需求 BO-1：基础画板显示
- 单页面展示一个 K 线图（默认 600px 高度）
- 图表库：**Lightweight Charts v5.x**（最新稳定版）
- 支持 K 线、MA、EMA、布林带等基础系列
- 鼠标交互：滚轮缩放、拖动、十字光标、tooltip
- 中文日期格式：`2026年08月11日`

#### 需求 BO-2：接收 K 线数据（API）
- **API 端点**：`POST /api/ohlcv`
- **请求体**：
  ```json
  {
    "ohlcv": [
      {"timestamp": 1714521600000, "open": 65000, "high": 65500, "low": 64800, "close": 65200, "volume": 1000}
    ]
  }
  ```
- **响应**：`{"status": "ok", "count": 365}`
- **前端行为**：WebSocket 推送 `ohlcv_update` 消息，前端更新图表（**不刷新页面**）

#### 需求 BO-3：加载本地 CSV（API）
- **API 端点**：`POST /api/load-csv`
- **请求体**：`{"path": "/mnt/Projects/data/btc_2024.csv"}`
- **响应**：`{"status": "ok", "rows": 365, "columns": ["timestamp", "open", "high", "low", "close", "volume"]}`
- **后端行为**：读取 CSV，转换为 K 线格式，存储到当前状态
- **前端行为**：自动更新图表

#### 需求 BO-4：执行 Python 脚本获取数据（API）
- **API 端点**：`POST /api/run-script`
- **请求体**：
  ```json
  {
    "script": "/mnt/Projects/my_indicators/bb.py",
    "func": "BB",
    "params": {"period": 20, "std_multiplier": 2},
    "name": "BB_20_2",
    "save_as": "indicator"
  }
  ```
- **后端行为**：
  1. 路径白名单检查（见第七章）
  2. 动态 import 用户 Python 文件
  3. 调用指定函数（class 或 function）
  4. 传入当前 K 线数据 + 用户参数
  5. 解析返回值（dict 或 list）
  6. 根据 `save_as` 保存为 K 线数据 或 指标
- **响应**：`{"status": "ok", "result_type": "indicator", "name": "BB_20_2"}`
- **前端行为**：自动更新图表

#### 需求 BO-5：添加/删除指标（API）
- **API 端点**：`POST /api/indicator`（添加）、`DELETE /api/indicator/{name}`（删除）
- **添加请求体**（单线模式）：
  ```json
  {
    "name": "MA_20",
    "type": "line",
    "values": [...],   // 与 K 线等长，允许 null
    "style": {"color": "#2196f3", "lineWidth": 2}
  }
  ```
- **添加请求体**（多线模式 🆕 v1.5）：
  ```json
  {
    "name": "MACD",
    "lines": [
      {"name": "MACD_main",   "type": "line",      "values": [...], "style": {...}},
      {"name": "MACD_signal", "type": "line",      "values": [...], "style": {...}},
      {"name": "MACD_hist",   "type": "histogram", "values": [...], "style": {...}}
    ],
    "subplot": "MACD"
  }
  ```
- **前端行为**：
  - 添加：图表上叠加新指标线/柱/区域
  - 删除：移除对应线

#### 需求 BO-5.1：指标 series 类型扩展 🆕 v1.5

**v1.5 扩展**（小 c 姐姐建议）：`type` 枚举从 `line/bar` 扩展到 5 种 + `markers`

**类型枚举**：

| type | Lightweight Charts 系列 | 用途 |
|------|------------------------|------|
| `line` | LineSeries | 折线（MA、EMA、Bollinger Bands 中轨等）|
| `area` | AreaSeries | 面积图（概率堆叠、区域填充）|
| `baseline` | BaselineSeries | 基线图（单一基准值对比）|
| `histogram` | HistogramSeries | 柱状图（MACD hist、成交量）|
| `step` | LineSeries + `lineType=WithSteps` | 阶梯线（离散状态机）|
| `bar` | HistogramSeries | ⚠️ **向后兼容别名**，推荐用 `histogram` |

**style 字段扩展**：

```json
{
  "style": {
    "color": "#2196f3",          // 现有 - 主色
    "lineWidth": 2,               // 现有 - 线宽
    "lineType": 0,                // 🆕 0=simple / 1=with_steps / 2=curved
    "fillOpacity": 0.3,           // 🆕 area 填充透明度 0-1
    "topColor": "#2196f3",        // 🆕 area 渐变顶色
    "bottomColor": "#2196f300",   // 🆕 area 渐变底色
    "baseValue": 0,               // 🆕 baseline 基准值
    "priceScaleId": "right"       // 🆕 指定 left / right / overlay 坐标轴
  }
}
```

**markers 概念**（任意 series 都能附加 markers）：

```json
{
  "name": "BBJudge",
  "type": "line",
  "values": [...],
  "style": {...},
  "markers": [
    {
      "time": 1714521600000,      // K 线 timestamp
      "position": "aboveBar",      // aboveBar / belowBar / inBar
      "color": "#ef5350",         // 红色
      "shape": "circle",          // circle / square / arrowUp / arrowDown
      "text": "状态不一致"        // 鼠标悬停文字
    }
  ]
}
```

**典型使用场景**（小 c 姐姐的 BBJudge 概率对比）：

```json
POST /api/indicator
{
  "name": "5_states_prob",
  "lines": [
    {"name": "fast_up",   "type": "area", "values": [...], "style": {"fillOpacity": 0.6, "topColor": "#26a69a80", "bottomColor": "#26a69a00"}},
    {"name": "slow_up",   "type": "area", "values": [...], "style": {"fillOpacity": 0.6, "topColor": "#42a5f580", "bottomColor": "#42a5f500"}},
    {"name": "ranging",   "type": "area", "values": [...], "style": {"fillOpacity": 0.6, "topColor": "#9e9e9e80", "bottomColor": "#9e9e9e00"}},
    {"name": "slow_down", "type": "area", "values": [...], "style": {"fillOpacity": 0.6, "topColor": "#ffa72680", "bottomColor": "#ffa72600"}},
    {"name": "fast_down", "type": "area", "values": [...], "style": {"fillOpacity": 0.6, "topColor": "#ef535080", "bottomColor": "#ef535000"}}
  ],
  "subplot": "5_states"
}
```

**注意**：所有视觉属性统一放 `style` 内（`fillOpacity` / `topColor` / `bottomColor` 等），顶层只保留结构字段（`name` / `type` / `values` / `style` / `markers` / `subplot` / `lines`）。

#### 需求 BO-5.2：NaN / null 处理约定 🆕 v1.5

**背景**：Python 指标脚本的 `rolling(20).mean()` 前 19 根是 NaN，`json.dumps` 默认输出 `NaN` 字面量不是合法 JSON，前端 `JSON.parse` 会直接抛异常。

**强制约定**（后端 + 脚本作者 + 前端）：

**1. 后端 normalize 机制**（所有脚本返回值强制过）：

```python
import math

def normalize(x):
    """NaN/Infinity → null，numpy/pandas 类型 → 原生 Python 类型"""
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x

def normalize_data(data):
    """递归遍历 dict / list，将 NaN/Inf 替换为 None"""
    if isinstance(data, dict):
        return {k: normalize_data(v) for k, v in data.items()}
    if isinstance(data, list):
        return [normalize_data(v) for v in data]
    return normalize(data)
```

**2. 前端 null 跳过**：
- `null` 视为「无值」
- 折线在该点断开（不连接）
- 柱跳过（不绘制）
- 面积跳过（不填充）
- 不报错

**3. 文档声明**：
- 指标脚本返回的 `values` 数组**允许包含 `null`**
- 语义：「该位置无有效值」（如预热期、rolling 不足）
- 后端自动 normalize，前端不需特殊处理

#### 需求 BO-5.3：values 与 K 线索引对齐约定 🆕 v1.5

**约定**：

> 指标 `values` 数组**与当前时间周期的 K 线等长**；预热期无值的位置用 `null` 占位；前端**按数组索引**与 K 线对齐（第 i 个 value 对应第 i 根 K 线）。长度不一致时后端返回 `INVALID_INPUT` 错误。

**实现要点**：

```python
# 后端校验
async def add_indicator(data: dict, board_id: str, timeframe: str):
    ohlcv = get_ohlcv(board_id, timeframe)
    expected_length = len(ohlcv)

    # 单线模式
    if "values" in data:
        if len(data["values"]) != expected_length:
            raise HTTPException(400, {
                "error": "INVALID_INPUT",
                "message": f"Indicator values length {len(data['values'])} != ohlcv length {expected_length}"
            })

    # 多线模式
    if "lines" in data:
        for line in data["lines"]:
            if len(line["values"]) != expected_length:
                raise HTTPException(400, {
                    "error": "INVALID_INPUT",
                    "message": f"Line {line['name']} values length mismatch"
                })
```

**前端使用**：

```javascript
// 第 i 根 K 线对应的指标值
function getIndicatorValue(indicator, candleIndex) {
    return indicator.values[candleIndex];  // 可能是 null
}

// 画图时跳过 null
const points = indicator.values.map((v, i) => ({
    time: ohlcv[i].time,
    value: v
})).filter(p => p.value !== null);  // 跳过 null
```

#### 需求 BO-5.4：state 持久化明确说明 🆕 v1.5

**v0.1 持久化策略**（v1.5 明确说明）：

> **画板配置在进程重启后会丢失**（v0.1 设计）。调试期可接受，**生产环境需升级到 L4 + Redis 持久化**（v1.0+ 路线图）。

**已保存的状态**（v0.1）：
- ✅ WebSocket 连接断开重连后自动恢复（数据在内存中）
- ❌ 服务重启后画板 / 时间周期 / 副图 / 指标 全部丢失

**用户自助保存**（v0.1 临时方案）：
- 调 `GET /api/state` 获取当前完整状态
- 自己保存成 JSON 文件
- 服务启动后调 `POST /api/board` + `POST /api/ohlcv` 等手动恢复

**v0.2+ 改进**：
- 启动时自动加载 `config.yaml` 里指定的"初始画板配置"
- 支持 `POST /api/save-state` 保存到本地文件
- 支持 `POST /api/load-state` 从文件恢复

**v1.0+ 持久化**：
- Redis 后端存储
- 自动持久化所有画板状态
- 重启后自动恢复

#### 需求 BO-6：图表状态保存与恢复
- 当前所有 K 线数据 + 指标保存在后端内存
- WebSocket 连接断开重连后，自动推送当前完整状态
- 不依赖 localStorage（避免前端篡改）

#### 需求 BO-7：副图管理 🆕
- **布局**：垂直堆叠（行业标准，副图都在主图下方）
- **高度**：用户自定义，默认 150px
- **可拖动**：副图顶部有拖动手柄，鼠标可拖动改变高度
- **拖动同步**：松手时才同步到后端（不是拖动过程中）
- **多副图支持**：可同时存在多个副图，每个副图可挂多个指标
- **删除时清理**：删除副图时，自动删除副图上的所有指标

**典型场景**：
- 副图 1：MACD（挂 MACD_main / MACD_signal / MACD_hist 三个指标）
- 副图 2：RSI（挂 RSI_14）
- 副图 3：OBV（挂 OBV_main）
- 副图数量 = 用户根据需要动态增减

#### 需求 BO-8：副图上的指标（复用主图 API）🆕
- 副图指标 = 复用现有 `/api/indicator` 接口 + `subplot` 字段
- **向后兼容**：`subplot` 字段可选，不传或传 `"main"` → 画在主图
- **副图标识**：传副图名（如 `"RSI"`）→ 画在该副图
- 副图必须已创建（通过 `POST /api/subplot`）

**示例**：
```json
// 主图指标（不指定 subplot）
POST /api/indicator
{"name": "MA_20", "type": "line", "values": [...]}

// 副图指标（指定 subplot）
POST /api/indicator
{"name": "RSI_14", "type": "line", "values": [...], "subplot": "RSI"}
```

#### 需求 BO-9：多画板管理 🆕

**类比**：类似 Excel 的多 Sheet 机制，目的是**横向对比研究**（多个标的并排看）

**核心场景**：
- 画板 1：BTCUSDT 1 年日线 + BB + MACD
- 画板 2：ETHUSDT 1 年日线 + BB + MACD
- 画板 3：SOLUSDT 1 年日线 + BB + MACD
- 三个画板**并存**，AI 可指定在哪个画板画，**无需清除前一个**

**设计原则**：
- ✅ **数据隔离**：每个画板独立的 K 线 / 指标 / 副图
- ✅ **当前画板**：后端维护一个"当前画板"概念（用户手动切换时更新）
- ✅ **API 显式指定**：AI 可通过 `?board_id=xxx` 直接操作任意画板，**不依赖当前画板**
- ✅ **向后兼容**：未指定 `board_id` 时操作当前画板（保持现有 API 行为）

**API 操作模式**：

| 模式 | 用法 | 典型场景 |
|------|------|----------|
| **隐式当前画板** | `POST /api/ohlcv` → 画在当前画板 | 用户手动切换后，AI 继续画 |
| **显式指定画板** | `POST /api/ohlcv?board_id=eth` → 画在 eth 画板 | AI 直接画到指定画板，**无需用户切换** |

**典型用户场景**：

```
用户："先画 BTC，画完看 BTC 画板"
AI:   POST /api/ohlcv                    # 画在当前画板
      POST /api/indicator?board_id=btc   # 也画在 btc 画板

用户："现在给 ETH 也画一下"（用户没说切换）
AI:   POST /api/ohlcv?board_id=eth      # ✅ 显式指定 eth，无需用户切换

用户："给之前的画板加点东西"
AI:   GET /api/boards                    # 先看有哪些画板
      POST /api/indicator?board_id=existing_board  # 直接画到已有画板
```

#### 需求 BO-10：画板 Tab 栏 UI 🆕

- 画板 Tab 栏（顶部）：`[BTC 1Y] [ETH 1Y] [SOL 1Y] [+ 添加]`
- 切换 Tab → 画板内容切换（自动调用 `GET /api/board/{id}`）
- 双击 Tab → 重命名画板（自动调用 `PUT /api/board/{id}`）
- 关闭按钮（×）→ 删除画板（自动调用 `DELETE /api/board/{id}`）
- 当前画板高亮显示
- "+" 按钮 → 弹出创建画板对话框（自动调用 `POST /api/board`）

#### 需求 BO-11：多时间周期（Timeframe）🆕

**类比**：同一画板内可有多个时间周期（如 1d + 4h + 1h），类似专业交易面板（TradingView / 同花顺）的"多周期同列"功能。

**核心场景**：
- 画板 "BTC 全周期"：1d + 4h + 1h + 15m
- 每个时间周期都有自己的 K 线 + 指标 + 副图
- **切换显示**（非垂直堆叠）：画板内一次只显示一个时间周期，通过时间周期 Tab 切换

**设计原则**：
- ✅ **数据隔离**：每个时间周期独立的 K 线 / 指标 / 副图
- ✅ **灵活创建**：画板创建时可指定多周期（`intervals: ["1d", "4h"]`），也可只创建单周期
- ✅ **动态管理**：画好后可插入 / 删除时间周期
- ✅ **当前时间周期**：后端维护一个"当前时间周期"概念（用户切换时更新）
- ✅ **API 显式指定**：AI 可通过 `?timeframe=xxx` 直接操作任意时间周期
- ✅ **向后兼容**：未指定 `timeframe` → 操作"默认时间周期"（通常是第一个）

**API 操作模式**：

| 模式 | 用法 | 典型场景 |
|------|------|----------|
| **隐式默认时间周期** | `POST /api/ohlcv?board_id=btc` → 画板默认时间周期 | 用户切换画板后，AI 继续画 |
| **显式指定时间周期** | `POST /api/ohlcv?board_id=btc&timeframe=4h` → 画板 4h 时间周期 | AI 直接画到指定时间周期 |

**多时间周期 vs 多画板**：

| 维度 | 多画板 (BO-9) | 多时间周期 (BO-11) |
|------|---------------|---------------------|
| 适用场景 | 横向对比（BTC vs ETH） | 同一标的不同维度（1d vs 4h）|
| Tab 层级 | 顶层 Tab | 画板内 Tab |
| 数据关系 | 完全独立 | 共享同一 symbol |
| 切换方式 | `GET /api/board/{id}` | `GET /api/board/{id}/timeframe/{tf}` |

#### 需求 BO-12：全脚本化数据源 🆕

**核心设计原则**：**所有数据源 = Python 脚本**，不区分静态/动态。

**统一思路**：
- 数据源脚本：输入参数 → 输出 K 线数据
- 指标脚本：输入 K 线 → 输出指标值
- 脚本内部实现自由（调 API / 读 CSV / 查 DB / 连 WebSocket / 任何方式）
- 后端只关心脚本输出格式是否符合规范

**优势**：
- ✅ 后端简化（只有"运行脚本"一个核心路径）
- ✅ 灵活性暴增（用户可混用任何数据获取方式）
- ✅ 学习曲线低（只需要会写 Python 函数）
- ✅ 未来扩展容易（加新数据源类型 = 写个 Python 脚本）

**脚本输出格式规范**（内部 K 线统一格式）：

```python
# 数据源脚本返回（必须）
[
    {
        "timestamp": 1714521600000,    # 必填，毫秒（13 位）
        "open": 65000,                  # 必填
        "high": 65500,                  # 必填
        "low": 64800,                   # 必填
        "close": 65200,                 # 必填
        "volume": 1000                  # 可选，缺失填 0
    },
    ...
]

# 指标脚本返回（多线）
{
    "bb_upper": [...],
    "bb_middle": [...],
    "bb_lower": [...]
}

# 指标脚本返回（单线）
{
    "values": [...]
}
```

**为什么不用 CCXT 数组格式**：
- CCXT 数组格式 `[ts, o, h, l, c, v]` 适合加密但不通用
- 各市场数据源格式不统一：CCXT 数组 / yfinance DataFrame / Tushare dict / Alpaca dict
- 内部 dict 格式可读性最好 + 跨市场兼容（加密/美股/A股全友好）
- 适配工作由数据源脚本承担（合理职责划分）

**各市场数据源脚本示例**（统一返回 dict）：

```python
# 加密（CCXT → 内部 dict）
def fetch_btc_ohlcv(symbol="BTCUSDT", interval="1d", limit=365):
    import ccxt
    exchange = ccxt.okx()
    raw = exchange.fetch_ohlcv(symbol, interval, limit=limit)
    return [
        {"timestamp": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
        for c in raw
    ]

# 美股（yfinance → 内部 dict）
def fetch_aapl_ohlcv(symbol="AAPL", period="1y", interval="1d"):
    import yfinance as yf
    df = yf.download(symbol, period=period, interval=interval)
    return [
        {
            "timestamp": int(ts.timestamp() * 1000),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row["Volume"])
        }
        for ts, row in df.iterrows()
    ]

# A 股（Tushare → 内部 dict）
def fetch_a_stock_ohlcv(ts_code="000001.SZ"):
    import tushare as ts
    pro = ts.pro_api("YOUR_TOKEN")
    df = pro.daily(ts_code=ts_code)
    return [
        {
            "timestamp": int(pd.Timestamp(row["trade_date"]).timestamp() * 1000),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["vol"])
        }
        for _, row in df.iterrows()
    ]

# CSV 文件
def read_csv_data(file_path="/mnt/Projects/data/btc.csv"):
    import pandas as pd
    df = pd.read_csv(file_path)
    return df.to_dict('records')

# 数据库
def fetch_from_db(symbol="BTCUSDT"):
    import sqlite3
    conn = sqlite3.connect("/mnt/Projects/data/ohlcv.db")
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE symbol=?", (symbol,))
    return [
        {"timestamp": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
        for r in cursor.fetchall()
    ]
```

**两个独立 API 概念**（哥哥明确要求不合并）：

| 概念 | API | 作用 | 输出格式 |
|------|-----|------|----------|
| **数据源** | `/api/board/{id}/timeframe/{tf}/datasource` | 输入参数 → 输出 K 线 | K 线列表（dict 格式）|
| **指标** | `/api/indicator` | 输入 K 线 → 输出指标值 | 单线 `{"values": [...]}` 或多线 `{name: [...]}` |

**实时数据源（轮询模式）**：
- 同一套脚本机制
- 加 `poll_interval` 参数（秒），后端每 N 秒调用一次
- 3 次失败后通知用户（指数退避）
- 输出格式与静态数据源完全一致（K 线 dict）
- 轮询时返回"最新 K 线"（不一定完整历史）

**自动重算机制**：
- 当时间周期的 K 线更新时（实时推送 / 手动刷新）
- 后端自动重算该时间周期下所有**指标脚本**
- WebSocket 推送 `indicator_refresh` 消息

---

### 3.3 数据源类型（统一脚本驱动）🆕 v1.4 重构

**v1.3 之前**：实时模式是独立模式（Tab 切换）

**v1.4 重构**：实时模式**并入数据源概念**，统一通过脚本实现

**详细规格见附录 D（数据源扩展指南）**

#### 3.3.1 数据源类型总览

| 类型 | 触发方式 | API | 实现 |
|------|----------|-----|------|
| **静态数据源** | 一次性 | `POST /api/board/{id}/timeframe/{tf}/datasource`（不传 poll_interval）| 脚本返回历史 K 线，跑一次完成 |
| **实时数据源** | 持续轮询 | 同上（传 `poll_interval: 5`）| 脚本返回最新 K 线，后端每 5 秒调用 |
| **动态指标** | K 线更新时自动重算 | `POST /api/indicator`（传 `script` 字段）| 脚本接收 K 线，返回指标值 |

**所有数据源 = 脚本，区别只在于调用频率和输出格式。**

#### 3.3.2 实时数据源详细设计

**触发方式**：用户传 polling 脚本，脚本内部实现如何获取实时数据。

```http
POST /api/board/btc/timeframe/1d/datasource
Content-Type: application/json

{
  "script": "/path/to/fetch_live.py",
  "func": "fetch_latest_ohlcv",
  "params": {"symbol": "BTCUSDT", "interval": "1d"},
  "poll_interval": 5
}
```

**后端行为**：
- 每 5 秒调用 `fetch_latest_ohlcv(symbol="BTCUSDT", interval="1d")`
- 脚本内部自由实现（调 OKX API / Binance WebSocket / 任何方式）
- 返回最新 K 线（dict 格式）
- 后端通过 WebSocket 推送 `ohlcv_update` 给前端

**轮询失败处理**：
- 3 次失败后通知用户（WebSocket 推送 `datasource_error`）
- 后端进入指数退避（5s → 10s → 30s → 60s）
- 用户可手动调 `POST /api/board/{id}/timeframe/{tf}/refresh` 强制重试

**停止实时数据源**：

```http
DELETE /api/board/btc/timeframe/1d/datasource
```

#### 3.3.3 动态指标自动重算

**当时间周期的 K 线更新时**（实时推送 / 手动刷新）：

1. 后端更新 `ohlcv` 数据
2. 扫描该时间周期下所有**指标脚本**
3. 对每个指标脚本，重新执行（传入新 K 线）
4. 更新指标值
5. WebSocket 推送 `indicator_refresh`

**手动重算单个指标**：

```http
POST /api/indicator/refresh/RSI_14?board_id=btc&timeframe=1d
```

**手动刷新整个时间周期**（重拉 K 线 + 重算所有指标）：

```http
POST /api/board/btc/timeframe/1d/refresh
```

#### 3.3.4 移除的独立"实时模式"功能

**v1.3 之前**的 5 个实时模式需求（RT-1~RT-5）已**合并到数据源 + 多时间周期**：
- RT-1 选择交易对 → 画板的 `symbol` 字段
- RT-2 选择 K 线周期 → 画板的 `intervals` 字段
- RT-3 实时数据推送 → 数据源 API（`poll_interval`）
- RT-4 默认指标 → 通过指标脚本添加
- RT-5 模式互不干扰 → 不再需要（v0.1 只有画板模式）

#### 3.3.5 `run-script` 与 `datasource` 的关系 🆕 v1.6

**问题**：两个 API 都能"跑脚本拿 K 线"，功能重叠，文档没解释关系。

**说明**：

| API | 用途 | 区别 |
|-----|------|------|
| `POST /api/run-script` + `save_as:"ohlcv"` | 一次性跑脚本拿数据 | **通用入口**，不支持轮询（向后兼容）|
| `POST /api/board/{id}/timeframe/{tf}/datasource`（不传 `poll_interval`） | 一次性跑脚本拿数据 | **语义更清晰**，挂在具体画板+时间周期上 |
| `POST /api/board/{id}/timeframe/{tf}/datasource`（传 `poll_interval`） | 持续轮询 | **实时数据源**，仅此 API 支持 |

**推荐使用**：
- **一次性加载数据** → 用 `datasource`（语义清晰 + 关联到画板）
- **实时轮询** → 必须用 `datasource`（`run-script` 不支持）
- **`run-script` 保留为通用入口**（向后兼容，未来可用于调试 / 临时跑脚本）

---

### 3.4 通用功能

#### 需求 CO-1：实时日志面板
- 页面底部有一个**日志面板**（可折叠）
- 显示：
  - API 调用记录
  - WebSocket 推送消息
  - 错误信息
- 日志条目带时间戳
- 最多保留 200 条

#### 需求 CO-2：当前状态显示
- 顶部状态栏显示：
  - 当前模式（v0.1 固定显示"画板模式"）
  - WebSocket 连接状态
  - 数据条数（如"K 线: 365 条 / 指标: 3 个"）

#### 需求 CO-3：API 文档展示
- 页面右下角"API 帮助"按钮
- 点击弹出文档，列出所有 REST API + WebSocket 消息格式

---

## 四、技术架构

### 4.1 整体架构

```
┌────────────────────────────────────────────────────────┐
│ 浏览器（HTML + JavaScript）                            │
│ ├─ K 线图（Lightweight Charts v5.x）                   │
│ ├─ 实时日志面板                                        │
│ └─ WebSocket 客户端                                    │
└────────────────────────────────────────────────────────┘
              ↕ HTTP REST + WebSocket
┌────────────────────────────────────────────────────────┐
│ FastAPI 后端（Python，端口 8000）                       │
│ ├─ REST API 端点                                       │
│ │  ├─ POST /api/ohlcv                                  │
│ │  ├─ POST /api/load-csv                               │
│ │  ├─ POST /api/run-script                             │
│ │  ├─ POST /api/indicator                              │
│ │  └─ DELETE /api/indicator/{name}                     │
│ ├─ WebSocket 端点 /ws                                   │
│ ├─ 数据存储（内存）                                     │
│ │  ├─ current_ohlcv                                    │
│ │  └─ current_indicators                               │
│ ├─ Python 执行器（基于 config.yaml 的白名单）           │
│ │  └─ v0.1: 直接 import + 调用                         │
│ │  └─ v0.2: 升级为 subprocess 隔离                     │
│ └─ 配置加载（config.yaml）                              │
└────────────────────────────────────────────────────────┘
```

### 4.2 技术栈

| 组件 | 选型 | 备注 |
|------|------|------|
| 后端框架 | FastAPI | 已安装 |
| WebSocket | FastAPI 内置 | - |
| 前端图表库 | **Lightweight Charts v5.x** | 顶级渲染 + 自定义灵活 |
| Python 执行 | importlib（L1） → subprocess（L2 升级） | 渐进式安全 |
| 配置文件 | **YAML**（`config.yaml`） | 见附录 C |
| 部署 | **手动 nohup**（v0.1） → systemd / docker（v0.2+） | 渐进式 |

---

## 五、API 详细规格

### 5.1 REST API

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/` | 返回画板 HTML |
| `POST` | `/api/board` | 创建画板（支持 `intervals` 字段指定多时间周期）🆕 |
| `GET` | `/api/boards` | 列出所有画板 |
| `GET` | `/api/board/{id}` | 切换当前画板 |
| `PUT` | `/api/board/{id}` | 更新画板（重命名）|
| `DELETE` | `/api/board/{id}` | 删除画板 |
| `POST` | `/api/board/{id}/timeframe` | 插入时间周期 🆕 |
| `DELETE` | `/api/board/{id}/timeframe/{tf}` | 删除时间周期 🆕 |
| `GET` | `/api/board/{id}/timeframes` | 列出所有时间周期 🆕 |
| `GET` | `/api/board/{id}/timeframe/{tf}` | 切换当前时间周期 🆕 |
| `POST` | `/api/ohlcv` | 直接传入 K 线数据（支持 `?board_id=xxx&timeframe=xxx`，可选 `markers` 字段 🆕）|
| `POST` | `/api/load-csv` | 加载本地 CSV 文件（支持 `?board_id=xxx&timeframe=xxx`）|
| `POST` | `/api/run-script` | 执行 Python 脚本获取数据（支持 `?board_id=xxx&timeframe=xxx`，通用入口）|
| `POST` | `/api/board/{id}/timeframe/{tf}/datasource` | 配置数据源（脚本 + 可选 `poll_interval`）🆕 v1.6 |
| `GET` | `/api/board/{id}/timeframe/{tf}/datasource` | 查看当前数据源状态 🆕 v1.6 |
| `DELETE` | `/api/board/{id}/timeframe/{tf}/datasource` | 停止数据源 🆕 v1.6 |
| `POST` | `/api/board/{id}/timeframe/{tf}/refresh` | 手动刷新（重拉 K 线 + 重算所有指标）🆕 v1.6 |
| `POST` | `/api/indicator` | 添加指标（支持 `subplot` 字段 + `lines` 数组 🆕 v1.5 + `markers` + `?board_id=xxx&timeframe=xxx`）|
| `DELETE` | `/api/indicator/{name}` | 删除指标（支持 `?board_id=xxx&timeframe=xxx`）|
| `POST` | `/api/indicator/refresh/{name}` | 手动重算单个指标 🆕 v1.6 |
| `POST` | `/api/markers` | 更新 K 线主图标记（覆盖式，全量替换）🆕 v1.6 |
| `POST` | `/api/subplot` | 创建副图（支持 `?board_id=xxx&timeframe=xxx`）|
| `PUT` | `/api/subplot/{name}` | 更新副图（高度、标题，支持 `?board_id=xxx&timeframe=xxx`）|
| `DELETE` | `/api/subplot/{name}` | 删除副图（同时删除其上所有指标，支持 `?board_id=xxx&timeframe=xxx`）|
| `GET` | `/api/subplots` | 列出所有副图（支持 `?board_id=xxx&timeframe=xxx`）|
| `GET` | `/api/state` | 获取当前完整状态（支持 `?board_id=xxx&timeframe=xxx`，调试用）|
| `GET` | `/api/config` | 查看当前生效的配置（只读）|
| `POST` | `/api/reload-config` | 重新加载 config.yaml（无需重启）|

**🆕 多画板 + 多时间周期关键设计**：
- 所有画板相关 API（除画板/时间周期管理外）都支持 `?board_id=xxx&timeframe=xxx` 可选查询参数
- **未指定 board_id** → 操作**当前画板**（向后兼容）
- **未指定 timeframe** → 操作**当前画板的默认时间周期**（向后兼容）
- **指定 board_id** → 操作**指定画板**（AI 自动化场景，**不依赖用户手动切换**）
- **指定 timeframe** → 操作**指定时间周期**（AI 自动化场景，**不依赖用户手动切换**）

#### API 详细规格

##### 0. 多画板管理 API 🆕

###### 0.1 POST /api/board（创建画板）

```http
POST /api/board
Content-Type: application/json

{
  "id": "btc",                          // 必填，画板唯一标识（如 btc / eth / sol）
  "name": "BTCUSDT 1年日线",           // 可选，显示名
  "symbol": "BTCUSDT",                  // 可选，关联的标的（用于未来显示）
  "interval": "1d"                      // 可选，关联的周期
}

→ 201 Created
{
  "status": "ok",
  "board": {
    "id": "btc",
    "name": "BTCUSDT 1年日线",
    "symbol": "BTCUSDT",
    "interval": "1d",
    "ohlcv_count": 0,
    "indicator_count": 0,
    "subplot_count": 0
  }
}
```

###### 0.2 GET /api/boards（列出所有画板）

```http
GET /api/boards

→ 200 OK
{
  "current_board": "btc",
  "boards": [
    {"id": "btc", "name": "BTCUSDT 1年日线", "symbol": "BTCUSDT", "interval": "1d", "ohlcv_count": 365, "indicator_count": 5, "subplot_count": 2},
    {"id": "eth", "name": "ETHUSDT 1年日线", "symbol": "ETHUSDT", "interval": "1d", "ohlcv_count": 365, "indicator_count": 3, "subplot_count": 1}
  ]
}
```

###### 0.3 GET /api/board/{id}（切换当前画板）

```http
GET /api/board/eth
// 等价于 POST /api/board/eth/switch

→ 200 OK
{
  "status": "ok",
  "current_board": "eth",
  "board": {
    "id": "eth",
    "name": "ETHUSDT 1年日线",
    "ohlcv_count": 365,
    "indicator_count": 3,
    "subplot_count": 1
  }
}
```

**副作用**：WebSocket 推送 `board_switch` 消息，前端自动重新加载该画板的完整状态。

###### 0.4 PUT /api/board/{id}（更新画板，重命名）

```http
PUT /api/board/btc
Content-Type: application/json

{
  "name": "BTC 1Y (BB20/2)"        // 新显示名
}

→ 200 OK
{
  "status": "ok",
  "board": {
    "id": "btc",
    "name": "BTC 1Y (BB20/2)"
  }
}
```

###### 0.5 DELETE /api/board/{id}（删除画板）

```http
DELETE /api/board/btc

→ 200 OK
{
  "status": "ok",
  "removed": "btc",
  "current_board": "eth"  // 如果删除的是当前画板，自动切到下一个
}
```

**注意**：
- 删除画板会同时清空该画板的所有 K 线、指标、副图
- 如果删除的是当前画板，自动切换到列表中的下一个画板
- 如果删除后没有任何画板，`current_board` 设为 `null`

###### 0.5a POST /api/board（修改：加 `intervals` 字段）🆕

```http
POST /api/board
Content-Type: application/json

{
  "id": "btc",                                    // 必填
  "name": "BTC 1Y 多周期",                       // 可选
  "symbol": "BTCUSDT",                            // 可选
  "intervals": ["1d", "4h", "1h"]                 // 🆕 可选，默认 ["1d"]
}

→ 201 Created
{
  "status": "ok",
  "board": {
    "id": "btc",
    "name": "BTC 1Y 多周期",
    "symbol": "BTCUSDT",
    "intervals": ["1d", "4h", "1h"],
    "default_timeframe": "1d"                     // 🆕 第一个时间周期为默认
  }
}
```

###### 0.6 POST /api/board/{id}/timeframe（插入时间周期）🆕

```http
POST /api/board/btc/timeframe
Content-Type: application/json

{
  "interval": "15m"        // 必填，时间周期标识（如 1m/5m/15m/30m/1h/4h/1d/1w）
}

→ 201 Created
{
  "status": "ok",
  "board_id": "btc",
  "timeframe": "15m",
  "ohlcv_count": 0,
  "indicator_count": 0,
  "subplot_count": 0
}
```

**副作用**：
- 在 `boards[btc]["timeframes"]["15m"]` 下创建空时间周期
- WebSocket 推送 `timeframe_create`
- 前端在画板内时间周期 Tab 栏显示新的 Tab

###### 0.7 DELETE /api/board/{id}/timeframe/{tf}（删除时间周期）🆕

```http
DELETE /api/board/btc/timeframe/4h

→ 200 OK
{
  "status": "ok",
  "board_id": "btc",
  "removed_timeframe": "4h",
  "removed_indicators": ["MA_20", "BB_20_2"],
  "removed_subplots": ["MACD", "RSI"]
}
```

**注意**：
- 不允许删除最后一个时间周期（至少要保留 1 个 → 返回 400 错误）
- 删除时间周期会同时清空该时间周期的所有 K 线、指标、副图
- 如果删除的是默认时间周期 → 自动设置列表中下一个为默认

###### 0.8 GET /api/board/{id}/timeframes（列出所有时间周期）🆕

```http
GET /api/board/btc/timeframes

→ 200 OK
{
  "board_id": "btc",
  "default_timeframe": "1d",
  "current_timeframe": "1d",
  "timeframes": [
    {"interval": "1d", "ohlcv_count": 365, "indicator_count": 5, "subplot_count": 2},
    {"interval": "4h", "ohlcv_count": 0, "indicator_count": 0, "subplot_count": 0},
    {"interval": "1h", "ohlcv_count": 0, "indicator_count": 0, "subplot_count": 0}
  ]
}
```

###### 0.9 GET /api/board/{id}/timeframe/{tf}（切换当前时间周期）🆕

```http
GET /api/board/btc/timeframe/4h
// 等价于 POST /api/board/btc/timeframe/4h/switch

→ 200 OK
{
  "status": "ok",
  "board_id": "btc",
  "current_timeframe": "4h",
  "state": {
    "ohlcv": [...],
    "indicators": {...},
    "subplots": {...}
  }
}
```

**副作用**：WebSocket 推送 `timeframe_switch` 消息，前端自动重新加载该时间周期的 K 线 + 指标 + 副图。

##### 1. POST /api/subplot（创建副图）

```http
POST /api/subplot
Content-Type: application/json

{
  "name": "MACD",               // 必填，唯一标识（不能为 "main"）
  "height": 150,                // 可选，默认 150px
  "title": "MACD(12,26,9)"     // 可选，默认与 name 相同
}

→ 201 Created
{
  "status": "ok",
  "subplot": {
    "name": "MACD",
    "height": 150,
    "title": "MACD(12,26,9)",
    "indicators": []
  }
}
```

##### 2. PUT /api/subplot/{name}（更新副图，主要是高度）

**触发场景**：用户拖动副图顶部手柄改变高度后调用

```http
PUT /api/subplot/MACD
Content-Type: application/json

{
  "height": 200,                // 必填（拖完后的新高度）
  "title": "MACD(12,26,9)"     // 可选，修改标题
}

→ 200 OK
{
  "status": "ok",
  "subplot": {
    "name": "MACD",
    "height": 200,
    "title": "MACD(12,26,9)",
    "indicators": ["MACD_main", "MACD_signal", "MACD_hist"]
  }
}
```

##### 3. DELETE /api/subplot/{name}（删除副图）

```http
DELETE /api/subplot/MACD

→ 200 OK
{
  "status": "ok",
  "removed": "MACD",
  "removed_indicators": ["MACD_main", "MACD_signal", "MACD_hist"]
  // 注意：副图上的指标也一并删除
}
```

##### 4. GET /api/subplots（列出所有副图，调试用）

```http
GET /api/subplots

→ 200 OK
{
  "subplots": [
    {
      "name": "MACD",
      "height": 150,
      "title": "MACD(12,26,9)",
      "indicators": ["MACD_main", "MACD_signal", "MACD_hist"]
    },
    {
      "name": "RSI",
      "height": 120,
      "title": "RSI(14)",
      "indicators": ["RSI_14"]
    }
  ]
}
```

##### 5. POST /api/indicator（修改：加 subplot 字段 + 同名覆盖）

```http
POST /api/indicator
Content-Type: application/json

{
  "name": "RSI_14",
  "type": "line",
  "values": [...],
  "subplot": "RSI",           // 🆕 可选
                                 //   - 不传 → "main"（画在主图，向后兼容）
                                 //   - "main" → 明确画在主图
                                 //   - "RSI" → 画在名为 RSI 的副图（必须已创建）
  "style": {"color": "#purple", "lineWidth": 1.5}
}

→ 200 OK
{
  "status": "ok",
  "indicator": "RSI_14",
  "subplot": "RSI"          // 返回确认画在了哪里
}
```

**🆕 v1.6 同名指标覆盖行为**：

```
同名指标再次提交 → 默认覆盖（更新 values/style/subplot）
                  → WebSocket 推送 `indicator_update`（而非 `indicator_add`）

理由：调参是最高频操作（如 BB(20) → BB(30)），不应报"已存在"。
如需禁止覆盖，传 `"replace": false`：
{
  "name": "RSI_14",
  "type": "line",
  "values": [...],
  "replace": false    // 🆕 显式禁止覆盖
}
→ 已存在 → 返回 400 INDICATOR_EXISTS 错误
```

**🆕 v1.6 单线 markers 字段**（指标系列上的标记）：

```json
POST /api/indicator
{
  "name": "BBJudge_signals",
  "type": "line",
  "values": [...],
  "markers": [           // 🆕 任意 line/area/histogram 都能附加 markers
    {
      "time": 1714521600000,
      "position": "aboveBar",
      "color": "#ef5350",
      "shape": "circle",
      "text": "状态不一致"
    }
  ]
}
```

##### 5.5 POST /api/markers 🆕 v1.6（K 线主图标记）

**用途**：直接在 K 线主图蜡烛图上标记关键点（最常用：BBJudge argmax 状态 ≠ 硬编码状态 的 bar 标红）。

```http
POST /api/markers?board_id=btc&timeframe=1d
Content-Type: application/json

{
  "markers": [
    {
      "time": 1714521600000,
      "position": "aboveBar",     // aboveBar / belowBar / inBar
      "color": "#ef5350",        // 红色
      "shape": "circle",         // circle / square / arrowUp / arrowDown
      "text": "状态不一致"      // 鼠标悬停文字
    }
  ]
}

→ 200 OK
{
  "status": "ok",
  "count": 1,
  "board_id": "btc",
  "timeframe": "1d"
}
```

**行为**：
- **覆盖式**：替换当前 K 线主图的所有 markers（全量替换，非追加）
- **清空**：传 `{"markers": []}` 即可清空
- WebSocket 推送 `markers_update` 消息
- 与指标系列的 `markers` 字段独立（主图 markers 和 indicator markers 分开管理）

##### 5.6 POST /api/ohlcv 加 `markers` 可选字段 🆕 v1.6

**用途**：随 K 线一起提交 markers（一次调用完成）。

```http
POST /api/ohlcv?board_id=btc&timeframe=1d
Content-Type: application/json

{
  "ohlcv": [
    {"timestamp": 1714521600000, "open": 65000, "high": 65500, "low": 64800, "close": 65200, "volume": 1000},
    ...
  ],
  "markers": [           // 🆕 可选 - 随 K 线一起提交
    {
      "time": 1714521600000,
      "position": "aboveBar",
      "color": "#ef5350",
      "shape": "circle",
      "text": "关键 K 线"
    }
  ]
}

→ 200 OK
{
  "status": "ok",
  "ohlcv_count": 365,
  "markers_count": 1
}
```

**vs 5.5 POST /api/markers 的区别**：
- `POST /api/ohlcv`：K 线 + markers 一起提交（一次性）
- `POST /api/markers`：单独更新 markers（K 线不变，只改标记）

### 5.2 WebSocket 消息格式

**服务端 → 客户端**：

| 消息类型 | 用途 | 数据格式 |
|---------|------|----------|
| `init` | 连接建立时推送**当前画板的当前时间周期**的完整状态 | `{type, data: {board_id, timeframe, ohlcv, indicators, subplots}}` ⬅️ 含 board_id + timeframe |
| `ohlcv_update` | K 线数据更新（当前画板当前时间周期）| `{type, board_id, timeframe, data: [...]}` ⬅️ 含 board_id + timeframe |
| `indicator_add` | 新指标添加（首次）| `{type, board_id, timeframe, name, values, subplot, style}` ⬅️ 含 board_id + timeframe |
| `indicator_update` | 同名指标覆盖（调参时）🆕 v1.6 | `{type, board_id, timeframe, name, values, subplot, style}` |
| `indicator_refresh` | 指标自动重算完成（K 线更新触发）🆕 v1.6 | `{type, board_id, timeframe, name, values, subplot}` |
| `indicator_remove` | 指标删除 | `{type, board_id, timeframe, name}` |
| `subplot_create` | 副图创建 | `{type, board_id, timeframe, name, height, title}` |
| `subplot_update` | 副图更新（高度变化）| `{type, board_id, timeframe, name, height, title}` |
| `subplot_remove` | 副图删除 | `{type, board_id, timeframe, name}` |
| `board_switch` | 画板切换 | `{type, board_id, state: {ohlcv, indicators, subplots}}` |
| `board_create` | 画板创建 | `{type, board: {...}}` |
| `board_remove` | 画板删除 | `{type, board_id, current_board}` |
| `timeframe_create` | 时间周期创建 🆕 | `{type, board_id, interval}` |
| `timeframe_remove` | 时间周期删除 🆕 | `{type, board_id, interval, default_timeframe}` |
| `timeframe_switch` | 时间周期切换 🆕 | `{type, board_id, timeframe, state: {ohlcv, indicators, subplots}}` |
| `datasource_start` | 数据源启动（含轮询配置）🆕 v1.6 | `{type, board_id, timeframe, poll_interval}` |
| `datasource_stop` | 数据源停止 🆕 v1.6 | `{type, board_id, timeframe}` |
| `datasource_error` | 数据源报错（3次失败后）🆕 v1.6 | `{type, board_id, timeframe, error, retry_after}` |
| `markers_update` | K 线主图 markers 更新 🆕 v1.6 | `{type, board_id, timeframe, markers: [...]}` |

**🆕 多画板 + 多时间周期设计**：
- 所有画板/时间周期相关消息都带 `board_id` + `timeframe` 字段
- 客户端根据 `board_id` + `timeframe` 判断作用在哪个画板哪个时间周期
- `board_switch` / `timeframe_switch` 消息会**重新推送完整数据**（前端可清空旧状态）

---

## 六、数据流示例（v0.1 画板模式）

### 6.1 基础场景：画 K 线 + 主图指标

```
[开发者操作]
1. 浏览器打开 http://localhost:8000
2. 默认进入"画板模式"
3. 页面显示空 K 线图

[Agent（小幺或小一）执行]
curl POST /api/run-script {
  script: "/path/to/fetch_btc.py",
  func: "get_btc_yearly",
  save_as: "ohlcv"
}
 → 后端运行脚本，拿到 365 条日线数据
 → WebSocket 推送 ohlv_update
 → 前端 K 线图显示 365 天 BTC 日线

curl POST /api/run-script {
  script: "/path/to/bb.py",
  func: "BB",
  params: {period: 20, std_multiplier: 2},
  name: "BB_20_2",
  save_as: "indicator"
}
 → 后端运行 BB 脚本，输出 upper/middle/lower
 → WebSocket 推送 indicator_add（subplot: "main"）
 → 前端在主图上叠加布林带

[开发者调整]
"BB 参数改成 period=20, std_multiplier=1.5"
 → Agent 再次调用 run-script
 → 图表自动更新（无需刷新页面）
```

### 6.2 副图场景：创建 MACD 副图 + 在上面画指标

```
[Agent 执行]

# Step 1: 创建副图
curl POST /api/subplot {
  name: "MACD",
  height: 150,
  title: "MACD(12,26,9)"
}
 → WebSocket 推送 subplot_create
 → 前端自动创建 MACD 副图

# Step 2: 计算 MACD 指标
curl POST /api/run-script {
  script: "/path/to/macd.py",
  func: "MACD",
  save_as: "indicator"
}
 → 返回 MACD 三条线

# Step 3: 在 MACD 副图上画三条线
curl POST /api/indicator {
  name: "MACD_main",
  type: "line",
  values: [...],
  subplot: "MACD"
}
curl POST /api/indicator {
  name: "MACD_signal",
  type: "line",
  values: [...],
  subplot: "MACD"
}
curl POST /api/indicator {
  name: "MACD_hist",
  type: "bar",
  values: [...],
  subplot: "MACD"
}

[开发者调整]
"我想让 MACD 副图更高一点"
 → 鼠标拖动 MACD 副图顶部手柄（前端纯客户端体验）
 → 松手时自动调用：curl PUT /api/subplot/MACD {height: 200}
 → WebSocket 推送 subplot_update
 → 副图高度变为 200px

[开发者清理]
"删除 MACD 副图"
 → 鼠标右键菜单 / API：curl DELETE /api/subplot/MACD
 → MACD 副图及其上所有指标一起删除
```

### 6.3 多画板场景：横向对比 BTC/ETH/SOL 🆕

```
[Agent 执行]

# Step 1: 创建 3 个画板
curl POST /api/board {id: "btc", name: "BTC 1Y", symbol: "BTCUSDT", interval: "1d"}
 → WebSocket: board_create
curl POST /api/board {id: "eth", name: "ETH 1Y", symbol: "ETHUSDT", interval: "1d"}
 → WebSocket: board_create
curl POST /api/board {id: "sol", name: "SOL 1Y", symbol: "SOLUSDT", interval: "1d"}
 → WebSocket: board_create

# Step 2: 用户先看 BTC，AI 在 BTC 画板上画
curl POST /api/ohlcv?board_id=btc {ohlcv: [...]}    # ✅ 显式指定 btc
curl POST /api/indicator?board_id=btc {name: "MA_20", ...}

# Step 3: 用户说"现在给 ETH 也画一下"（没说切换）
curl POST /api/ohlcv?board_id=eth {ohlcv: [...]}    # ✅ 显式指定 eth，无需切换
curl POST /api/indicator?board_id=eth {name: "MA_20", ...}

# Step 4: 用户手动点 ETH Tab 切换
curl GET /api/board/eth
 → WebSocket: board_switch {board_id: "eth", state: {...}}
 → 前端自动加载 ETH 画板的 K 线 + 指标

# Step 5: 用户说"给之前 BTC 画板加个 MACD"
curl GET /api/boards    # AI 看看有哪些画板
curl POST /api/subplot?board_id=btc {name: "MACD", ...}    # 显式指定 btc
curl POST /api/indicator?board_id=btc {name: "MACD_main", ..., "subplot": "MACD"}    # 画在 btc 画板的 MACD 副图

[用户拖动画板 Tab 重命名 / 关闭]
 → 前端双击 Tab → 自动调用 PUT /api/board/{id}
 → 前端点击 × → 自动调用 DELETE /api/board/{id}
```

### 6.4 多时间周期场景：BTC 1d/4h/1h 🆕

```
[Agent 执行]

# Step 1: 创建带多时间周期的画板
curl POST /api/board {
  id: "btc_multi",
  name: "BTC 多周期",
  symbol: "BTCUSDT",
  intervals: ["1d", "4h", "1h"]    # 一次创建 3 个时间周期
}
 → WebSocket: board_create + timeframe_create × 3
 → 默认时间周期: "1d"

# Step 2: 用户先看 1d（默认时间周期）
curl POST /api/ohlcv?board_id=btc_multi {ohlcv: [...]}    # 默认画在 1d
curl POST /api/indicator?board_id=btc_multi {name: "MA_20", ...}    # 1d 的 MA

# Step 3: 用户说"4h 也画一下"
curl POST /api/ohlcv?board_id=btc_multi&timeframe=4h {ohlcv: [...]}    # ✅ 显式指定 4h
curl POST /api/indicator?board_id=btc_multi&timeframe=4h {name: "MA_20", ...}    # 4h 的 MA

# Step 4: 用户切换到 4h
curl GET /api/board/btc_multi/timeframe/4h
 → WebSocket: timeframe_switch {board_id: "btc_multi", timeframe: "4h", state: {...}}
 → 前端自动加载 4h 的 K 线 + 指标

# Step 5: 画板已经画好了 1d + 4h，现在用户说"加个 15m"
curl POST /api/board/btc_multi/timeframe {interval: "15m"}    # 插入新时间周期
curl POST /api/ohlcv?board_id=btc_multi&timeframe=15m {ohlcv: [...]}

# Step 6: 用户说"4h 不用了，删掉"
curl DELETE /api/board/btc_multi/timeframe/4h
 → WebSocket: timeframe_remove
 → 4h 时间周期连同指标、副图一起删除

[用户切换时间周期 Tab]
 → 前端点击 [1d] / [4h] / [1h] / [15m] Tab → 自动调用 GET /api/board/{id}/timeframe/{tf}
 → 前端显示对应时间周期的 K 线 + 指标
```

---

## 七、安全考虑

### 7.1 Python 沙箱：渐进式演进

#### 当前 v0.1：L1（仅路径白名单）
- 配置文件 `config.yaml` 定义可执行路径白名单
- 后端在 `run-script` 时检查路径
- 不做其他限制（团队互信 + 内网使用）

#### 未来 v0.2：L2（subprocess 隔离）
- 升级触发：暴露死循环 / 资源问题后
- 改动：仅替换后端实现层，API 不变
- 配置文件切 `execution.enable_subprocess: true`

#### 未来 v0.3：L3/L4
- L3：RestrictedPython（受限语法）
- L4：Docker 容器隔离
- API 仍不变

### 7.2 路径白名单机制

- 路径列表定义在 `config.yaml` 的 `script_paths` 字段
- 路径列表定义在 `script_exclude_paths` 作为黑名单
- **多路径支持**：可以配置多个允许的目录
- **可热重载**：修改 config.yaml 后调用 `POST /api/reload-config` 即可生效

### 7.3 CORS 与网络安全

- 仅允许同源访问（localhost / 内网 IP）
- 跨域请求需要明确配置
- v0.1 不对外开放（仅内网）

### 7.4 v0.1 阶段禁止的 API（开发期规范）

为防止误用，文档里**明确列出禁止操作**：

```python
# ❌ 禁止：可能搞坏服务
os.system(...)          # shell 命令
subprocess.Popen(...)   # 子进程
os.fork()               # fork 炸弹
while True: pass        # 死循环（v0.2 会有超时保护）

# ✅ 推荐：纯计算
def BB(ohlcv_data, period=20):
    df = pd.DataFrame(ohlcv_data)
    return {...}
```

---

## 八、部署与运维

### 8.1 部署位置

- 服务跑在 `172.20.0.3`（哥哥的容器内网 IP）
- 端口：`8000`
- 访问方式：`http://172.20.0.3:8000` 或通过映射端口

### 8.2 启动方式（v0.1 手动 nohup）

```bash
# 启动
cd /mnt/Projects/agentkline && nohup python3 server.py > /tmp/agentkline.log 2>&1 &

# 停止
pkill -f "python3.*server.py"

# 重启
pkill -f "python3.*server.py" && cd /mnt/Projects/agentkline && nohup python3 server.py > /tmp/agentkline.log 2>&1 &
```

### 8.3 日志

- 服务端日志：`/tmp/agentkline.log`
- 前端日志：浏览器控制台 + 页面内嵌日志面板

### 8.4 未来部署演进

- **v0.2**：systemd unit 文件（开机自启 + 自动重启）
- **v0.3+**：Docker 镜像（跨环境部署）

---

## 九、迭代计划

### v0.1（当前需求）
- [x] 需求确认（YAML 配置 + Lightweight Charts + L1 沙箱）
- [ ] 画板模式：K 线 + 5 个 REST API + WebSocket 推送
- [ ] 前端实时日志面板
- [ ] API 文档展示
- [ ] config.yaml 配置文件

### v0.2（计划）
- [ ] 模式切换 Tab（画板 + 实时行情）
- [ ] 实时行情模式：交易对/周期选择 + 5 秒轮询
- [ ] Python 沙箱升级 L2（subprocess + 超时）
- [ ] systemd 部署

### v0.3（远期）
- [ ] 实时模式自定义指标
- [ ] 多图表对比模式
- [ ] 指标结果导出 CSV
- [ ] 接入 Vibe-Trading MCP 实时数据

### v1.0（开源准备）
- [ ] Python 沙箱升级 L3/L4
- [ ] Docker 镜像
- [ ] 完整 README + 文档站
- [ ] CI/CD 流水线

---

## 十、已确认事项 ✅

| # | 确认项 | 决定 |
|---|--------|------|
| 1 | 图表库 | ✅ **Lightweight Charts v5.x**（最新稳定版） |
| 2 | 实时数据（v0.1） | ✅ **暂不实现**，重点在画板 |
| 3 | 实时数据（v0.2） | ✅ v0.2 计划实现 |
| 4 | Python 沙箱 | ✅ **L1 先行**（路径白名单），可配置多路径，后期升级 L2/L3/L4 |
| 5 | 部署 | ✅ v0.1 手动 nohup，后期扩展 systemd / docker |
| 6 | 配置文件格式 | ✅ **YAML**（`config.yaml`） |
| 7 | 路径白名单 | ✅ 配置多路径（见附录 C） |
| 8 | 路径可热重载 | ✅ `POST /api/reload-config` |

---

## 附录 A：Python 指标脚本约定

### 模式 1：函数模式（推荐）

```python
# /mnt/Projects/indicators/bb.py

def BB(ohlcv_data, period=20, std_multiplier=2):
    """
    ohlcv_data: list of dict, [{'timestamp': ..., 'open': ..., 'high': ..., 'low': ..., 'close': ..., 'volume': ...}, ...]
    返回: dict, {'bb_upper': [...], 'bb_middle': [...], 'bb_lower': [...]}
    """
    import pandas as pd
    df = pd.DataFrame(ohlcv_data)
    df['bb_middle'] = df['close'].rolling(period).mean()
    df['bb_std'] = df['close'].rolling(period).std()
    return {
        'bb_upper': (df['bb_middle'] + std_multiplier * df['bb_std']).tolist(),
        'bb_middle': df['bb_middle'].tolist(),
        'bb_lower': (df['bb_middle'] - std_multiplier * df['bb_std']).tolist(),
    }
```

### 模式 2：类模式

```python
class BB:
    def __init__(self, period=20, std_multiplier=2):
        self.period = period
        self.std_multiplier = std_multiplier

    def __call__(self, ohlcv_data):
        # 同函数模式
        ...
```

### 调用方式（API）

```json
{
    "script": "/mnt/Projects/indicators/bb.py",
    "func": "BB",
    "params": {"period": 20, "std_multiplier": 2},
    "save_as": "indicator"
}
```

### 堆叠面积图约定（v1.6）

**场景**：5 态概率要堆叠成「总面积 = 1」，需要把概率做**累积和（cumsum）**再画 5 条 area。

**约定**：**脚本端算 cumsum**（保持前端只做"画"不做"算"）。

```python
# 脚本端：5 态概率 → 5 条累积面积
def stack_probs(prob_rows):
    """
    prob_rows: [{fast_up:.., slow_up:.., ranging:.., slow_down:.., fast_down:..}, ...]
    返回 5 条累积数组（第 i 条 = 前 i 态概率之和）
    """
    import numpy as np
    order = ["fast_up", "slow_up", "ranging", "slow_down", "fast_down"]
    cums = {state: [] for state in order}
    for row in prob_rows:
        running_sum = 0
        for state in order:
            running_sum += row[state]
            cums[state].append(running_sum)
    return cums    # {"fast_up": [0.3, 0.3, ...], "slow_up": [0.5, 0.5, ...], ...}
```

**前端使用**：
- 脚本端输出 5 条 area 的**累积值**（非原始概率）
- 前端按 `type:"area"` 直接画，不做任何堆叠逻辑
- 堆叠顺序由脚本端控制（`lines` 数组顺序 = 从底到顶）
- 最底层 area 的 `style.bottomColor` 用透明（避免遮挡）

**示例**（完整的 BBJudge 堆叠）：

```python
# 脚本端
def BBJudge_stacked(prob_rows):
    """返回 5 条累积面积 + 主线 markers"""
    import numpy as np

    # 1. 计算累积值（堆叠逻辑在脚本端）
    order = ["fast_up", "slow_up", "ranging", "slow_down", "fast_down"]
    cums = {state: [] for state in order}
    for row in prob_rows:
        running = 0
        for state in order:
            running += row[state]
            cums[state].append(running)

    # 2. 主线 markers（不一致 bar 标红）
    hardcoded_state = [...]  # 硬编码状态序列
    judge_state = [...]     # BBJudge 输出序列
    markers = []
    for i, (h, j) in enumerate(zip(hardcoded_state, judge_state)):
        if h != j:
            markers.append({
                "time": prob_rows[i]["timestamp"],
                "position": "aboveBar",
                "color": "#ef5350",
                "shape": "circle",
                "text": f"不一致：硬编码={h}, BBJudge={j}"
            })

    return {
        "lines": [
            {"name": "fast_up",   "type": "area", "values": cums["fast_up"],   "style": {"fillOpacity": 0.6, "bottomColor": "#26a69a00", "topColor": "#26a69a80"}},
            {"name": "slow_up",   "type": "area", "values": cums["slow_up"],   "style": {"fillOpacity": 0.6, "bottomColor": "#42a5f500", "topColor": "#42a5f580"}},
            {"name": "ranging",   "type": "area", "values": cums["ranging"],   "style": {"fillOpacity": 0.6, "bottomColor": "#9e9e9e00", "topColor": "#9e9e9e80"}},
            {"name": "slow_down", "type": "area", "values": cums["slow_down"], "style": {"fillOpacity": 0.6, "bottomColor": "#ffa72600", "topColor": "#ffa72680"}},
            {"name": "fast_down", "type": "area", "values": cums["fast_down"], "style": {"fillOpacity": 0.6, "bottomColor": "#ef535000", "topColor": "#ef535080"}}
        ],
        "markers": markers
    }
```

---

## 附录 B：错误码

| 错误码 | 含义 | 触发场景 |
|--------|------|----------|
| `SCRIPT_NOT_FOUND` | 脚本文件不存在 | 路径错误 |
| `SCRIPT_PATH_DENIED` | 脚本路径不在白名单 | 配置错误或路径变更 |
| `FUNC_NOT_FOUND` | 函数/类不存在 | 脚本中无指定名字 |
| `TIMEOUT` | 执行超时 | 脚本运行 >30 秒（v0.2 启用） |
| `INVALID_INPUT` | 输入参数错误 | JSON Schema 校验失败 / indicator values 长度与 ohlcv 不匹配 |
| `EXEC_ERROR` | 脚本执行异常 | Python 运行时错误 |
| `SUBPLOT_EXISTS` | 副图名重复 | 已存在同名副图 |
| `SUBPLOT_NOT_FOUND` | 副图不存在 | 删除/更新/查询不存在的副图 |
| `SUBPLOT_NAME_INVALID` | 副图名不合法 | 副图名不能是 "main"（保留字）|
| `BOARD_EXISTS` | 画板 ID 重复 | 已存在同名画板 |
| `BOARD_NOT_FOUND` | 画板不存在 | 删除/更新/查询不存在的画板 |
| `BOARD_ID_INVALID` | 画板 ID 不合法 | ID 包含特殊字符或保留字 |
| `TIMEFRAME_EXISTS` | 时间周期已存在 🆕 | 同画板内已存在该时间周期 |
| `TIMEFRAME_NOT_FOUND` | 时间周期不存在 🆕 | 删除/查询不存在的时间周期 |
| `TIMEFRAME_LAST` | 不能删除最后一个时间周期 🆕 | 画板至少要有 1 个时间周期 |
| `INDICATOR_EXISTS` | 同名指标已存在（`replace:false` 时）🆕 v1.6 | 显式禁止覆盖时 |

---

## 附录 C：config.yaml 配置示例

完整配置文件（提交到 git 作为示例）：

```yaml
# ============================================
# AgentKline 配置文件
# ============================================
# 修改后调用 POST /api/reload-config 即可生效
# 无需重启服务
# ============================================

# 服务监听端口
server:
  host: "0.0.0.0"
  port: 8000

# Python 脚本执行路径白名单
# 支持多个路径（数组形式）
# 路径必须以 / 结尾表示目录
script_paths:
  - /mnt/Projects/indicators/      # 官方指标库
  - /mnt/Projects/my_indicators/   # 个人指标
  - /mnt/Projects/agentkline/tests/  # 测试脚本

# 排除路径（黑名单，优先级高于白名单）
script_exclude_paths:
  - /mnt/Projects/secrets/         # 即使在白名单内也拒绝

# Python 执行器配置
execution:
  # 超时时间（秒）- v0.2 启用
  timeout_seconds: 30

  # 内存限制（MB）- v0.2 启用
  memory_limit_mb: 512

  # 是否启用 subprocess 隔离
  # false: v0.1 直接 import（L1）
  # true: v0.2 升级为 subprocess（L2）
  enable_subprocess: false

# WebSocket 配置
websocket:
  # 客户端重连间隔
  reconnect_interval: 5

  # 心跳间隔（秒）
  heartbeat_interval: 30

# 日志配置
logging:
  # 服务端日志级别: DEBUG / INFO / WARNING / ERROR
  level: INFO

  # 日志文件路径
  file: /tmp/agentkline.log

  # 日志最大行数
  max_lines: 2000
```

### 使用方式

```bash
# 1. 复制示例配置
cp /mnt/Projects/agentkline/config.example.yaml /mnt/Projects/agentkline/config.yaml

# 2. 根据需要修改 config.yaml
vim /mnt/Projects/agentkline/config.yaml

# 3. 启动服务
cd /mnt/Projects/agentkline && nohup python3 server.py > /tmp/agentkline.log 2>&1 &

# 4. 运行时修改配置（无需重启）
curl -X POST http://localhost:8000/api/reload-config
```

### 文件结构（开源准备）

```
agentkline/
├── config.example.yaml    # 示例配置（提交到 git）
├── config.yaml            # 实际配置（加入 .gitignore）
├── server.py              # FastAPI 主程序
├── static/
│   └── board.html         # 画板页面
├── docs/
│   └── PRD-*.md
├── requirements.txt       # Python 依赖
├── README.md              # 项目说明
├── LICENSE                # 许可证
└── .gitignore             # git 忽略文件
```

`.gitignore` 应包含：

```
config.yaml
__pycache__/
*.pyc
/tmp/
*.log
```

---

## 附录 D：数据源扩展指南（v1.4 整合）

> **状态**：✅ v1.4 已实现

### D.1 全脚本化设计原则

**核心思想**：所有数据获取和指标计算 = Python 脚本，**后端只负责调度和适配**。

**三种脚本类型**：

| 类型 | 输入 | 输出 | API |
|------|------|------|-----|
| **数据源脚本** | params | `[{timestamp, open, high, low, close, volume}, ...]` | `POST /api/board/{id}/timeframe/{tf}/datasource` |
| **指标脚本（单线）** | ohlcv + params | `{"values": [...]}` | `POST /api/indicator` |
| **指标脚本（多线）** | ohlcv + params | `{line1: [...], line2: [...], ...}` | `POST /api/indicator` |

### D.2 内部 K 线统一格式（v1.4 选定）

**选择 dict 格式而非 CCXT 数组格式**的理由：
- 跨市场最通用（加密/美股/A股/CSV/DB 全部友好）
- 字段名清晰可读
- pandas 直接用 `pd.DataFrame(data)`
- JSON 序列化友好
- 跟 Lightweight Charts 字段名接近（前端易适配）

**字段规范**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `timestamp` | int (毫秒) | ✅ | Unix 时间戳 × 1000 |
| `open` | float | ✅ | 开盘价 |
| `high` | float | ✅ | 最高价 |
| `low` | float | ✅ | 最低价 |
| `close` | float | ✅ | 收盘价 |
| `volume` | float | ⚠️ | 成交量（缺失填 0）|

### D.3 各市场数据源脚本示例

#### 加密（CCXT）

```python
def fetch_btc_ohlcv(symbol="BTCUSDT", interval="1d", limit=365):
    import ccxt
    exchange = ccxt.okx()
    raw = exchange.fetch_ohlcv(symbol, interval, limit=limit)
    return [
        {"timestamp": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
        for c in raw
    ]
```

#### 美股（yfinance）

```python
def fetch_aapl_ohlcv(symbol="AAPL", period="1y", interval="1d"):
    import yfinance as yf
    df = yf.download(symbol, period=period, interval=interval)
    return [
        {
            "timestamp": int(ts.timestamp() * 1000),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row["Volume"])
        }
        for ts, row in df.iterrows()
    ]
```

#### A 股（Tushare）

```python
def fetch_a_stock_ohlcv(ts_code="000001.SZ"):
    import tushare as ts
    pro = ts.pro_api("YOUR_TOKEN")
    df = pro.daily(ts_code=ts_code)
    return [
        {
            "timestamp": int(pd.Timestamp(row["trade_date"]).timestamp() * 1000),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["vol"])
        }
        for _, row in df.iterrows()
    ]
```

#### CSV 文件

```python
def read_csv_data(file_path="/mnt/Projects/data/btc.csv"):
    import pandas as pd
    df = pd.read_csv(file_path)
    return df.to_dict('records')
```

#### 数据库（SQLite）

```python
def fetch_from_db(symbol="BTCUSDT"):
    import sqlite3
    conn = sqlite3.connect("/mnt/Projects/data/ohlcv.db")
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE symbol=?", (symbol,))
    return [
        {"timestamp": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
        for r in cursor.fetchall()
    ]
```

#### WebSocket 实时（同步包装）

```python
import asyncio
import websockets
import json

async def _fetch_ws(symbol):
    async with websockets.connect("wss://stream.example.com/ohlcv") as ws:
        msg = await ws.recv()
        return json.loads(msg)

def fetch_latest_ohlcv(symbol="BTCUSDT"):
    return [asyncio.run(_fetch_ws(symbol))]
```

### D.4 实时数据源配置示例

**v1.4 之前**：实时模式是独立 Tab，需要切换模式

**v1.4 之后**：实时数据源**直接挂在时间周期上**，与静态数据源统一接口

```http
POST /api/board/btc/timeframe/1d/datasource
{
  "script": "/path/to/fetch_live.py",
  "func": "fetch_latest_ohlcv",
  "params": {"symbol": "BTCUSDT", "interval": "1d"},
  "poll_interval": 5
}
```

**关键点**：
- ✅ 加 `poll_interval` 参数即变成实时数据源
- ✅ 脚本内部自由实现（OKX / Binance / WebSocket / DB / 任何）
- ✅ 输出格式与静态数据源完全一致（K 线 dict）
- ✅ 失败重试 + 指数退避 + 通知用户

### D.5 v1.4 移除的"实时模式"功能

v1.3 之前的 5 个实时模式需求（RT-1~RT-5）已**完全合并到数据源 + 多时间周期**：

| 旧需求 | 新实现 |
|--------|--------|
| RT-1 选择交易对 | 画板的 `symbol` 字段 + 时间周期独立 symbol |
| RT-2 选择 K 线周期 | 画板的 `intervals` 字段（可多周期）|
| RT-3 实时数据推送 | 数据源 API + `poll_interval` |
| RT-4 默认指标 | 指标脚本（`POST /api/indicator`）|
| RT-5 模式互不干扰 | 不再需要（v0.1 只有画板模式）|

---

## 附录 E：性能优化指南（v1.4 未来参考）📚

> **状态**：📅 未来参考（v1.4 不实现）
> **优先级**：当前 v0.1 重点是**功能完整性**，性能优化放在功能完成之后

### E.1 概述

**v0.1 性能预期**（基于 Lightweight Charts Canvas 渲染 + Python 脚本）：

| 场景 | 数据量 | 性能 |
|------|--------|------|
| **1 个画板 + 1 个时间周期 + 5 指标** | 365 K 线 | 60 FPS / CPU < 5% |
| **5 个画板 + 10 个时间周期 + 30 指标** | 5,000 K 线 | 60 FPS / CPU < 20% |
| **10 个画板 + 50 个时间周期 + 100 指标** | 50,000 K 线 | 30-60 FPS / CPU < 50% |
| **极端 1m × 1Y** | 525,000 K 线 | 需降采样（详见 E.6）|

**WebSocket 推送延迟**：单消息 < 10ms，批量（100ms 合并）< 110ms

**指标重算时间**：简单 < 50ms / 中等 < 200ms / 复杂 < 1s

### E.2 智能重算（避免重复计算）

**场景**：实时数据源推送 K 线更新时，**只在必要时重算指标**

**检测逻辑**：

```python
async def on_ohlcv_update(board_id, timeframe, new_ohlcv):
    old_ohlcv = get_ohlcv(board_id, timeframe)
    
    # 1. K 线完全没变 → 跳过
    if new_ohlcv == old_ohlcv:
        return
    
    # 2. 只更新最后一根 K 线（实时场景，常见）→ 增量重算
    if (len(new_ohlcv) == len(old_ohlcv) and
        all(new_ohlcv[i] == old_ohlcv[i] for i in range(len(new_ohlcv) - 1))):
        # 只重算最后一根的指标值
        incremental_recalc_indicators(board_id, timeframe, new_ohlcv[-1])
    else:
        # 3. 完整 K 线变化（手动刷新 / 切换时间周期）→ 完整重算
        full_recalc_indicators(board_id, timeframe, new_ohlcv)
```

**性能收益**：实时场景下从"每秒重算 N 个指标" → "每秒只重算最后一根"，CPU 占用降低 **90%**。

### E.3 指标结果缓存

**场景**：同一 K 线 + 同一参数 + 同一指标脚本 → 缓存结果，避免重复计算

**实现**：

```python
# 缓存 key：(画板, 时间周期, 指标名, K 线 hash, 参数 hash)
indicator_cache = {}

def get_or_compute_indicator(board_id, timeframe, name, ohlcv, script, func, params):
    cache_key = (board_id, timeframe, name, hash(tuple(ohlcv)), hash(tuple(sorted(params.items()))))
    
    if cache_key in indicator_cache:
        return indicator_cache[cache_key]  # 命中缓存
    
    # 未命中，执行脚本
    values = execute_script(script, func, ohlcv, params)
    indicator_cache[cache_key] = values
    return values
```

**缓存失效策略**：
- LRU（最近最少使用）
- 内存上限 100MB
- 画板删除时清空该画板的所有缓存

**性能收益**：相同 K 线多次访问 → 0 计算。

### E.4 WebSocket 推送合并

**场景**：短时间内多画板 / 多指标 / K 线更新 → 合并推送，减少网络开销

**实现**：

```python
ws_buffer = []
ws_timer = None

async def push_websocket(msg):
    ws_buffer.append(msg)
    
    if ws_timer is None:
        ws_timer = asyncio.create_task(delayed_push())

async def delayed_push():
    await asyncio.sleep(0.1)  # 100ms 合并窗口
    await ws.send(json.dumps({
        "type": "batch",
        "messages": ws_buffer
    }))
    ws_buffer.clear()
    ws_timer = None
```

**性能收益**：100ms 内的所有变更打包成 1 条消息 → 网络包数减少 70-90%。

### E.5 多画板 / 多时间周期资源管理

**场景**：10+ 画板同时活跃 → 内存 / CPU / WebSocket 资源管理

**策略**：

| 资源 | 限制 | 超出时策略 |
|------|------|-----------|
| **内存** | 单画板 ≤ 50MB | LRU 清理（淘汰最近最少访问） |
| **CPU** | 指标重算单次 ≤ 200ms | 超过则降级（只重算最后一根）|
| **WebSocket** | 单连接推送 ≤ 100 条/秒 | 合并推送（E.4）|
| **磁盘** | 画板配置不持久化 | 进程重启后丢失（v0.1 设计）|

**LRU 清理示例**：

```python
from collections import OrderedDict

class LRUCache(OrderedDict):
    def __init__(self, max_size):
        super().__init__()
        self.max_size = max_size
    
    def get(self, key):
        if key in self:
            self.move_to_end(key)
            return self[key]
        return None
    
    def put(self, key, value):
        if key in self:
            self.move_to_end(key)
        self[key] = value
        if len(self) > self.max_size:
            self.popitem(last=False)  # 淘汰最久未使用
```

### E.6 自动降采样（1m / 5m 大量数据）

**场景**：1m × 1Y = 525,000 K 线 → 前端渲染 + 指标计算压力

**策略**：

```python
def maybe_downsample(ohlcv, max_points=10000):
    if len(ohlcv) <= max_points:
        return ohlcv
    
    # 保留策略：最新 5000 完整 + 旧数据降采样到 5000
    keep_recent = max_points // 2
    downsample_old_target = max_points // 2
    
    recent = ohlcv[-keep_recent:]
    old = ohlcv[:-keep_recent]
    
    # 旧数据降采样（每 N 根取 1 根）
    factor = max(1, len(old) // downsample_old_target)
    old_downsampled = old[::factor]
    
    return old_downsampled + recent
```

**触发条件**：
- 自动：`len(ohlcv) > 10000` → 降采样到 5000
- 用户手动：提供 API `POST /api/ohlcv/downsample?target=5000`

**降采样标记**：
- 在 K 线数据上加 `"downsampled": true` 字段
- 前端提示用户："数据已降采样，原始数据请用 `?full=true` 参数"

### E.7 Python 脚本执行优化

**场景**：频繁调用 Python 脚本（实时数据源 + 指标重算）

**优化策略**：

| 策略 | 实现 | 收益 |
|------|------|------|
| **子进程复用** | 持久化 Python 进程池，避免每次 fork | 启动开销 -80% |
| **预编译字节码** | `.pyc` 缓存 | 加载时间 -30% |
| **依赖预加载** | 启动时 import 常用库（pandas/numpy/ccxt）| 调用延迟 -50% |
| **结果序列化缓存** | 同一输入 → 同一输出（用 hash 缓存）| 重复计算 -100% |

**子进程复用示例**（v0.2 升级到 L2 时启用）：

```python
# L2 sandbox 子进程池
process_pool = ProcessPoolExecutor(max_workers=4)

def execute_user_script_subprocess(script_path, func_name, *args, **kwargs):
    future = process_pool.submit(
        run_in_subprocess, script_path, func_name, args, kwargs
    )
    return future.result(timeout=30)
```

### E.8 性能基准（验收标准）

**v0.1 性能基线**（验收时需达标）：

| 场景 | 数据量 | 验收标准 |
|------|--------|----------|
| 1 画板 + 1 时间周期 + 5 指标 | 365 K 线 | 60 FPS / 切换延迟 < 100ms / 指标重算 < 200ms |
| 5 画板 + 5 时间周期 + 20 指标 | 2,000 K 线 | 30-60 FPS / 切换延迟 < 200ms / 指标重算 < 1s |
| 10 画板 + 10 时间周期 + 50 指标 | 5,000 K 线 | 30 FPS / 切换延迟 < 500ms / 指标重算 < 2s |

**WebSocket 推送**：
- 单消息延迟 < 50ms（局域网）
- 批量推送 100ms 合并窗口

**API 响应时间**：
- `GET /api/boards` < 50ms
- `POST /api/ohlcv` < 100ms
- `POST /api/board/{id}/timeframe/{tf}/datasource`（首次执行）< 5s（取决于脚本）
- `POST /api/board/{id}/timeframe/{tf}/datasource`（轮询）< 1s
- `POST /api/indicator/refresh/{name}` < 500ms

### E.9 性能监控（v0.2+）

**监控指标**：

| 指标 | 阈值 | 告警 |
|------|------|------|
| WebSocket 推送延迟 | < 100ms | > 500ms 告警 |
| API 响应时间 P99 | < 1s | > 3s 告警 |
| Python 脚本执行时间 P99 | < 1s | > 5s 告警 |
| 内存占用 | < 500MB | > 1GB 告警 |
| CPU 占用 | < 50% | > 80% 告警 |

**实现**：v0.1 在 `/api/state` 增加性能统计字段；v0.2 集成 Prometheus。

### E.10 性能优化路线图

| 阶段 | 优化项 | 触发条件 |
|------|--------|----------|
| **v0.1** | 无（功能优先）| 性能基线达标即可 |
| **v0.2** | E.4 推送合并 + E.3 缓存 | 多个画板同时活跃时 |
| **v0.3** | E.2 智能重算 + E.7 子进程复用 | 实时场景性能瓶颈 |
| **v1.0** | E.5 资源管理 + E.6 自动降采样 | 100+ 画板 / 1m×1Y 场景 |
| **v1.0+** | E.9 性能监控 + 告警 | 生产环境部署 |

---

> **文档结束**
> **v1.6 已确认（最终版）**：在小一最终审阅 + 小 c 附录细节基础上完成了文档补全（API 端点 / WebSocket 消息 / 同名指标覆盖 / markers 端点 / 堆叠面积图约定）
> PRD 完整度 100%，可直接转发给小一/小c 开工

## 关键变更记录

- **v1.6 (2026-08-24)**：小一姐姐最终审阅 + 小 c 姐姐附录细节全部采纳
  - **补 6 个 API 端点到 5.1 表格**（小一 修正1）：
    - `POST /api/board/{id}/timeframe/{tf}/datasource`（配置数据源）
    - `GET /api/board/{id}/timeframe/{tf}/datasource`（查看状态）
    - `DELETE /api/board/{id}/timeframe/{tf}/datasource`（停止数据源）
    - `POST /api/board/{id}/timeframe/{tf}/refresh`（手动刷新）
    - `POST /api/indicator/refresh/{name}`（手动重算单个指标）
    - `POST /api/markers`（K 线主图标记）🆕 新增
  - **补 5 个 WebSocket 消息到 5.2 表格**（小一 修正2）：
    - `indicator_update`（同名指标覆盖）
    - `indicator_refresh`（指标自动重算）
    - `datasource_start` / `datasource_stop` / `datasource_error`
    - `markers_update`（K 线主图 markers）
  - **加 `run-script` 与 `datasource` 关系说明**（小一 修正3）：详细解释两个 API 的区别和使用场景
  - **新增 `POST /api/markers` 详细规格**（小一 修正4）：K 线主图标记专用端点
  - **修正 BBJudge 示例 JSON**（小一 + 小 c 附-1）：`fillOpacity` 统一放 `style` 内，补 `topColor` / `bottomColor` 渐变示例
  - **附录 A 补堆叠面积图约定**（小一 + 小 c 附-3）：脚本端算 cumsum，前端只画不算，完整 BBJudge 堆叠脚本示例
  - **同名指标覆盖行为**（小一 决定6）：默认 `replace: true`，传 `replace: false` 禁止覆盖 → `INDICATOR_EXISTS` 错误
  - **`POST /api/ohlcv` 加 `markers` 可选字段**（小一 + 小 c 附-2 方案 A）：K 线 + markers 一次提交
  - **小 c 姐姐附-3 完整采纳**：堆叠面积图 cumsum 责任方明确为脚本端，给出 5 态概率堆叠的完整脚本模板
  - **新增错误码**：`INDICATOR_EXISTS`（v1.6）
  - **画板 Tab 标题显示**（小一补充建议 3）：Tab 显示 `symbol + interval` 而非仅 `id`
  - 文档大小：约 76KB → 约 90KB（+14KB，+约 300 行）
  - **4 项开发期实现决定**（小一）：写入 HEARTBEAT.md 给小一参考
    - K 线样式硬编码默认（涨绿跌红）
    - 切换画板/时间周期时重置视口
    - 前端状态栏显示脚本执行进度
    - 前端单文件 `static/board.html`（不构建）
    - Lightweight Charts 用本地文件（不用 CDN）
  - **三方达成一致**：架构不动 / 功能完整 / 文档对齐 ✅
  - **PRD 完整度 100%** → 可正式开工

- **v1.5 (2026-08-24)**：小 c 姐姐审阅修订版
  - **新增 BO-5.1：series 类型扩展**（小 c 姐姐 P0-1）
    - `type` 枚举从 `line/bar` 扩展到 `line/area/baseline/histogram/step` + `bar` 向后兼容别名
    - `style` 字段新增 6 个属性（lineType / fillOpacity / topColor / bottomColor / baseValue / priceScaleId）
    - 新增 `markers` 概念（任意 series 都能附加 markers，用于标记关键点/状态不一致 bar）
  - **新增 BO-5.2：NaN/null 处理约定**（小 c 姐姐 P0-2）
    - 后端强制 normalize（NaN/Inf → null）
    - 前端跳过 null（折线断开 / 柱跳过 / 面积跳过）
    - 文档声明 values 允许包含 null
  - **新增 BO-5.3：values 与 K 线索引对齐约定**（小 c 姐姐 P1-1）
    - values 数组与 K 线等长
    - 长度不一致返回 `INVALID_INPUT` 错误
  - **新增 BO-5.4：state 持久化明确说明**（小 c 姐姐 P1-3）
    - v0.1 进程重启后画板配置丢失（明确写清）
    - 用户自助保存方案（GET /api state + 手动恢复）
    - v0.2+ 改进方向（save-state / load-state API）
    - v1.0+ 持久化（Redis）
  - **多线类型混合**（小 c 姐姐 P1-2 + 哥哥选择 A v0.1 支持）
    - `POST /api/indicator` 支持 `lines` 数组模式
    - 每条线独立 `type` + `values` + `style`
    - 解决 MACD 三条线类型不同（line + histogram）问题
  - 文档大小：约 67.5KB → 约 80KB（+12.5KB，+约 300 行）
  - **关键场景**（小 c 姐姐的 BBJudge 5 态概率对比）现在能完整实现：
    - 副图 1 "状态概率"：5 个 area 堆叠（fast_up / slow_up / ranging / slow_down / fast_down）
    - 副图 2 "硬编码对比"：step 阶梯线
    - 差异标记：markers（argmax 状态 ≠ 硬编码状态 的 bar 标红）
  - **小 c 姐姐的 5 个建议全部采纳并实现**

- **v1.4.1 (2026-08-24)**：附录 E 性能优化指南（v1.4 未来参考）
  - 新增附录 E：性能优化指南（10 个章节）
  - 性能优化策略：智能重算 / 缓存 / 推送合并 / 资源管理 / 自动降采样 / 脚本优化
  - 性能基准（验收标准）：1/5/10 画板场景的具体性能指标
  - 性能监控：v0.2+ 集成 Prometheus
  - 性能优化路线图：v0.1（无）→ v0.2（推送合并+缓存）→ v0.3（智能重算）→ v1.0（资源管理+降采样）→ v1.0+（监控告警）
  - **明确**：当前 v0.1 重点是功能完整性，性能优化放在功能完成之后
  - **两个关键问题**（哥哥提问）：
    1. **使用体验**：Lightweight Charts 是 TradingView 开源版本，Canvas 渲染引擎一致，使用体验 ≈ TradingView；但无内置指标（v1.4 全脚本化设计完美弥补）
    2. **性能**：单图 10 万 K 线流畅、多画板+多时间周期 CPU < 20%、实时数据源延迟 < 1s；极端 1m×1Y 需降采样（但 99% 场景无压力）

- **v1.4 (2026-08-24)**：全脚本化数据源 + 移除独立实时模式
  - 新增需求 BO-12：全脚本化数据源（统一接口：脚本 = 数据源 / 指标 / 一切）
  - **关键架构变化**：移除"实时模式"独立章节（3.3），并入数据源概念
  - **关键设计决策**：K 线统一格式选 **B 内部 dict 格式**（而非 CCXT 数组），理由：
    - 跨市场最通用（加密/美股/A股/CSV/DB 全友好）
    - pandas 直接 `pd.DataFrame(data)` 使用
    - 字段名清晰可读
    - JSON 序列化友好
  - **关键设计决策**：数据源 API 和指标 API **完全独立**（不合并）
    - 数据源：`POST /api/board/{id}/timeframe/{tf}/datasource`（输入 params → 输出 K 线）
    - 指标：`POST /api/indicator`（输入 ohlcv + params → 输出指标值）
  - 实时数据源 = 数据源 + `poll_interval` 参数（统一接口）
  - 轮询失败处理：3 次自动重试 + 指数退避（5s → 10s → 30s → 60s）+ 通知用户
  - 动态指标：K 线更新时自动重算（WebSocket 推送 `indicator_refresh`）
  - 新增 4 个 API：`POST/GET/DELETE /api/board/{id}/timeframe/{tf}/datasource` + `POST /api/board/{id}/timeframe/{tf}/refresh` + `POST /api/indicator/refresh/{name}`
  - 新增 3 个 WebSocket 消息：`datasource_start` / `datasource_stop` / `datasource_error` / `indicator_refresh`
  - 各市场数据源脚本示例（CCXT / yfinance / Tushare / CSV / SQLite / WebSocket）
  - 内部 K 线字段规范（timestamp 毫秒 / open/high/low/close/volume）
  - 文档大小：约 38KB → 约 48KB（+10KB，+约 200 行）
  - **设计决策**（3 个哥哥选定的推荐点）：
    - K 线格式：**B 内部 dict 格式**（跨市场最通用）
    - CSV 上传：**A 路径方式 + 脚本读 CSV**（保留现有 load-csv API）
    - API 概念：哥哥明确要求**两个独立 API**（数据源 vs 指标，不合并）
  - **哥哥的关键洞察**：
    1. "既然当前动态数据是自己写脚本实现，那静态数据也是运行脚本" → 启发全脚本化
    2. "数据源脚本是一个单独 api 来指定，指标脚本是另一个 api 来指定" → 明确 API 分工
    3. "脚本内部实现是什么不用管" → 给用户最大灵活性
  - **PRD 完整度 100%**（v0.1 所有需求已明确）→ 可直接转发给小一/小c 开工

- **v1.3 (2026-08-24)**：新增多时间周期（Timeframe）功能
  - 新增需求 BO-11：多时间周期（同画板内多个时间周期，类比专业交易面板的多周期功能）
  - 新增 4 个 REST API：`POST /api/board/{id}/timeframe`（插入）/ `DELETE /api/board/{id}/timeframe/{tf}`（删除）/ `GET /api/board/{id}/timeframes`（列出）/ `GET /api/board/{id}/timeframe/{tf}`（切换）
  - 修改 `POST /api/board`：加 `intervals` 字段（支持创建时指定多时间周期）
  - **关键架构变化**：K 线 / 指标 / 副图 从 Board 移到 Timeframe 下
    - 旧：Board {ohlcv, indicators, subplots}
    - 新：Board {timeframes: {1d: {ohlcv, indicators, subplots}, 4h: {...}, 1h: {...}}}
  - **关键设计**：所有画板数据 API 加 `?timeframe=xxx` 可选参数
  - **关键设计**：未指定 timeframe → 操作画板默认时间周期（向后兼容）
  - **关键设计**：指定 timeframe → AI 可直接操作任意时间周期，**无需用户手动切换**
  - **关键设计**：不指定 board_id → 操作当前画板；不指定 timeframe → 操作默认时间周期（向后兼容）
  - 新增 3 个 WebSocket 消息：`timeframe_create` / `timeframe_remove` / `timeframe_switch`
  - 所有画板/时间周期相关 WebSocket 消息都带 `board_id` + `timeframe` 字段
  - 新增 3 个错误码：`TIMEFRAME_EXISTS` / `TIMEFRAME_NOT_FOUND` / `TIMEFRAME_LAST`
  - 新增数据流示例 6.4：多时间周期完整流程
  - 文档大小：约 32KB → 约 38KB（+6KB，+约 200 行）
  - **设计决策**（3 个哥哥选定的推荐点）：
    - 多时间周期布局：B **切换显示**（非垂直堆叠，类似专业交易面板）
    - 画板创建时：A **灵活**（`intervals` 数组，可单可多）
    - API 概念：A **新建独立 timeframe 概念**（从 Board 独立出来）
  - **哥哥的话**："可能还有最后一条" → 等待 v1.4

- **v1.2 (2026-08-24)**：新增多画板管理功能（横向对比研究场景）
  - 新增需求 BO-9：多画板管理（类比 Excel 多 sheet，横向对比 BTC/ETH/SOL 等）
  - 新增需求 BO-10：画板 Tab 栏 UI（双击重命名 / × 关闭 / + 添加 / 切换高亮）
  - 新增 5 个 REST API：`POST /api/board` / `GET /api/boards` / `GET /api/board/{id}` / `PUT /api/board/{id}` / `DELETE /api/board/{id}`
  - **关键设计**：所有画板相关 API（除画板管理外）支持 `?board_id=xxx` 可选参数
  - **关键设计**：未指定 `board_id` → 操作当前画板（向后兼容）
  - **关键设计**：指定 `board_id` → AI 可直接操作任意画板，**无需用户手动切换**
  - 新增 3 个 WebSocket 消息：`board_create` / `board_switch`（含新画板完整 state） / `board_remove`（含新 current_board）
  - 所有画板相关 WebSocket 消息都带 `board_id` 字段
  - 新增 3 个错误码：`BOARD_EXISTS` / `BOARD_NOT_FOUND` / `BOARD_ID_INVALID`
  - 新增数据流示例 6.3：多画板横向对比完整流程
  - 文档大小：24.5KB → 约 32KB（+7.5KB，+约 200 行）
  - **设计决策**（4 个哥哥选定的推荐点）：
    - board_id 传递方式：`?board_id=xxx` 可选查询参数（向后兼容）
    - WebSocket 策略：只推当前画板的更新（简单）
    - board_id 来源：用户自定义（如 btc / eth / sol）
    - 画板切换方式：显式调用 `GET /api/board/{id}` 切换
  - **哥哥补充的关键洞察**：AI 自动化场景中，API 可指定目标画板，**用户不需要手动切换**，这让多画板管理工作流完全自动化

- **v1.1 (2026-08-24)**：新增副图管理功能
  - 新增需求 BO-7：副图管理（垂直堆叠 + 可拖动高度 + 多副图 + 删除清理）
  - 新增需求 BO-8：副图上的指标（复用 `/api/indicator` + `subplot` 字段）
  - 新增 4 个 REST API：`POST /api/subplot` / `PUT /api/subplot/{name}` / `DELETE /api/subplot/{name}` / `GET /api/subplots`
  - 修改 `POST /api/indicator`：新增 `subplot` 字段（不传=主图，传副图名=画在副图）
  - 新增 3 个 WebSocket 消息：`subplot_create` / `subplot_update` / `subplot_remove`
  - 修改 `init` 消息：新增 `subplots` 字段；修改 `indicator_add` 消息：新增 `subplot` 字段
  - 新增 3 个错误码：`SUBPLOT_EXISTS` / `SUBPLOT_NOT_FOUND` / `SUBPLOT_NAME_INVALID`
  - 新增数据流示例 6.2：副图场景完整流程
  - 文档大小：18.4KB → 24.5KB（+6.1KB，+212 行）
  - **设计决策**（4 个哥哥选定的推荐点）：
    - 拖动手柄位置：副图顶部（行业标准）
    - 拖动同步时机：松手时同步（不是拖动过程中）
    - 高度持久化：后端存储（WebSocket 重连后可恢复）
    - API 风格：`PUT /api/subplot/{name}`（RESTful 语义）

- **v1.0 (2026-08-11)**：确认所有技术选型，移除实时模式实现（v0.1 重点画板），添加 YAML 配置附录
