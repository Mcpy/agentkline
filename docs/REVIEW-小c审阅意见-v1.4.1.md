# 画板 PRD 审阅意见（小c）

> **审阅人**：小c（量化交易算法专家，画板未来主要使用者之一）
> **审阅对象**：`PRD-交互式K线画板与实时行情.md` v1.4.1（1906 行）
> **审阅日期**：2026-08-24
> **审阅角度**：以「状态概率序列可视化 + 硬编码状态机对比」这一真实使用场景为基准，检验 PRD 能否支撑我们的核心需求

---

## 一、总体结论

架构方向**完全正确**，以下设计请保留不动：

- ✅ 多画板 + 多时间周期（横向对比 BTC/ETH、纵向多周期）
- ✅ 全脚本化数据源（直接接我们 `regime-detector/` 的 Python 脚本）
- ✅ API 显式指定 `?board_id=xxx&timeframe=xxx`（AI 自动化不依赖手动切换）
- ✅ 渐进式沙箱 L1→L4
- ✅ 副图垂直堆叠布局

但存在 **2 个 P0 缺口**（会卡住我们的核心场景）+ **3 个 P1 问题**，需在开发前补进 PRD。

---

## 二、P0 缺口（必须补，否则画板对我们没用）

### P0-1：series 类型太窄 —— 只有 `line` / `bar`

**现状**：`POST /api/indicator` 的 `type` 只支持 `line` / `bar`，`style` 只有 `color` + `lineWidth`。

**问题**：我们要做的「BBJudge 5 态概率可视化 + 硬编码状态机对比」需要 3 种 PRD 没有的 series 类型：

| 我们需要的类型 | 用途 | Lightweight Charts 对应 | PRD 现状 |
|---------------|------|:---:|:---:|
| **area**（面积图） | 5 态概率堆叠面积图 | `AreaSeries` | ❌ 缺 |
| **step**（阶梯线） | 硬编码状态机的离散状态序列 | `LineSeries + lineType=WithSteps` | ❌ 缺 |
| **markers / 区间高亮** | 两版状态不一致的 bar 标红 | `setMarkers` / 自定义背景 | ❌ 缺 |

> 说明：Lightweight Charts **完全原生支持**这三种，PRD 只是在 indicator API 里没把它们列出来，是**文档遗漏**，不是技术选型限制。加枚举值即可，不推翻架构。

**建议修改**：

1. `type` 枚举从 `line / bar` 扩展到：

```json
{
  "type": "line | area | baseline | histogram | step"
}
```

| type | 对应系列 | 说明 |
|------|---------|------|
| `line` | LineSeries | 折线（现有，保留）|
| `area` | AreaSeries | 面积图，用于概率堆叠 / 区域填充 |
| `baseline` | BaselineSeries | 基线图，单一基准值对比 |
| `histogram` | HistogramSeries | 柱状（原 `bar` 更名，`bar` 保留为别名向后兼容）|
| `step` | LineSeries + `lineType=WithSteps` | 阶梯线，离散状态机 |

2. `style` 字段扩展：

```json
{
  "style": {
    "color": "#2196f3",       // 现有
    "lineWidth": 2,            // 现有
    "lineType": 0,             // 🆕 0=simple / 1=with_steps / 2=curved
    "fillOpacity": 0.3,        // 🆕 area 填充透明度 0-1
    "topColor": "#2196f3",     // 🆕 area 渐变顶色
    "bottomColor": "#2196f300",// 🆕 area 渐变底色
    "baseValue": 0,            // 🆕 baseline 基准值
    "priceScaleId": "right"    // 🆕 指定 left / right / overlay 坐标轴
  }
}
```

3. **markers**：独立概念，非 series type。建议二选一：

- 方案 A（推荐）：给任意 series 支持 `markers` 数组（`{time, position, color, shape, text}`），用于在 K 线/指标上标记关键点；
- 方案 B：允许 `type: "histogram"` 的 0/1 稀疏柱，用来标记「不一致 bar」的位置。

> 我们的实际需求是「BBJudge argmax 状态 ≠ 硬编码状态 的 bar 用颜色标出来」，方案 A（series markers）或方案 B（稀疏柱高亮）都能满足，具体实现由你定。

### P0-2：指标 NaN / 空值处理未定义

**现状**：PRD 通篇没提 NaN 处理。

**问题**：Python 指标脚本的 `rolling(20)` 前 19 根是 NaN，我们 BBJudge 预热期前 24 根也是占位值。**NaN 不是合法 JSON**（`json.dumps` 默认输出 `NaN` 字面量，前端 `JSON.parse` 直接抛异常）。第一个真实脚本（BB 布林带）跑出来就会崩在序列化这一步。

**建议修改**（写进 PRD，作为后端强制约定）：

1. **后端 normalize**：所有脚本返回值（数据源 + 指标）出口统一过一遍转换：

```python
def normalize(x):
    """NaN/Infinity → null，numpy/pandas 类型 → 原生类型"""
    import math
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x
```

2. **前端跳过 null**：`null` 视为「无值」，折线在该点断开、柱跳过、面积跳过，不报错。

3. **明确声明**：指标脚本返回的 `values` 数组**允许包含 `null`**，语义为「该位置无有效值」。

---

## 三、P1 问题（次优先，建议一起补）

### P1-1：values 对齐语义未定义

指标 `values` 数组与 K 线索引的对应关系没有写清楚。

**建议约定**：

> 指标 `values` 数组**与当前时间周期的 K 线等长**；预热期无值的位置用 `null` 占位；前端**按数组索引**与 K 线对齐（第 i 个 value 对应第 i 根 K 线）。长度不一致时后端返回 `INVALID_INPUT` 错误。

### P1-2：多线指标类型不能混合

多线指标 `{macd_main: [...], macd_hist: [...]}` 一次返回，但类型统一继承，无法让 hist 那条是柱状、其余是折线。当前 BO-8 靠「拆成 3 次 `/api/indicator` 分别指定 type」绕过——说明问题存在但没在 API 层解决，使用方要拆，麻烦。

**建议**：多线指标返回值支持**按名字指定类型**：

```json
POST /api/indicator
{
  "name": "MACD",
  "lines": [
    {"name": "MACD_main",  "type": "line",      "values": [...]},
    {"name": "MACD_signal","type": "line",      "values": [...]},
    {"name": "MACD_hist",  "type": "histogram", "values": [...]}
  ],
  "subplot": "MACD"
}
```

> 若嫌改动大，可在 P0-1 扩展 type 枚举时一并支持「多线对象中每条线带独立 `type`」，不必新增独立 API。

### P1-3：state 持久化需明确标注

v0.1 画板配置「进程重启后丢失」，调试期可接受，但要在 PRD 里**明确写清**（当前散落在附录 E.5 表格里），避免我们调半天、服务重启就丢。

---

## 四、附：我们的真实使用场景（供你理解动机）

**场景**：BBJudge 状态判断器的概率输出 vs 旧硬编码状态机，逐根对比。

```
画板: BTC 1Y（1d）
├── 主图: K 线 + BB 三线（line）
└── 副图1 "状态概率"（area 堆叠）
    ├── fast_up   概率序列（area，fillOpacity=0.6）
    ├── slow_up   概率序列（area，fillOpacity=0.6）
    ├── ranging   概率序列（area，fillOpacity=0.6）
    ├── slow_down 概率序列（area，fillOpacity=0.6）
    └── fast_down 概率序列（area，fillOpacity=0.6）
└── 副图2 "硬编码对比"（step）
    └── 旧状态机离散序列（step，5 档取值）
└── 差异标记（markers / 稀疏柱）
    └── argmax 状态 ≠ 硬编码状态 的 bar 标红
```

这个场景直接依赖 **P0-1（area/step/markers）** 和 **P0-2（null 占位，预热期前 24 根）**，缺一不可。

---

## 五、给修改的优先级建议

| 优先级 | 项 | 动作 |
|:---:|------|------|
| **P0** | P0-1 series 类型扩展 | 扩 `type` 枚举 + `style` 字段 + markers 概念 |
| **P0** | P0-2 NaN/null 处理 | 后端 normalize + 前端跳过 null + 文档声明 |
| **P1** | P1-1 values 对齐 | 补一条约定 |
| **P1** | P1-2 多线类型混合 | `lines` 数组每条带 `type` |
| **P1** | P1-3 持久化标注 | 文档里写清楚 |

---

> **本审阅意见仅为补充需求，不推翻 PRD 现有架构**。小幺改完后，请回复，我们再一起复审，达成一致后再交给小一开工。

---

# 复审（v1.5）

> **复审日期**：2026-08-24
> **复审结论**：✅ **通过**。小幺已将 5 个建议（P0-1 / P0-2 / P1-1 / P1-2 / P1-3）全部采纳并落实到 PRD v1.5（新增 BO-5.1 ~ BO-5.4 + 多线模式），且补得比预期更细——含后端 `normalize` 代码、前后端对齐校验代码、BBJudge 典型场景 JSON。

**技术细节核对结果**（对照 Lightweight Charts v5 真实 API）：

| 核对项 | PRD 写法 | 是否正确 |
|--------|---------|:---:|
| `lineType` 枚举 | `0=simple / 1=with_steps / 2=curved` | ✅ |
| markers `position` | `aboveBar / belowBar / inBar` | ✅ |
| markers `shape` | `circle / square / arrowUp / arrowDown` | ✅ |
| `bar` 别名 | 向后兼容，推荐 `histogram` | ✅ |

**无硬伤，可开工。**

---

# 附录：3 个实现细节（开发期注意项，非框架级问题）

> 以下 3 点不阻塞开工，属于实现层面的澄清/可选增强，建议小一开工时对齐，或在开发期顺手定掉。

## 附-1：`fillOpacity` 位置统一

**问题**：style 字段定义里 `fillOpacity` 在 `style` 内：

```json
"style": { "fillOpacity": 0.3 }
```

但 BBJudge 典型场景示例里 `fillOpacity` 直接写在 line 顶层：

```json
{"name": "fast_up", "type": "area", "fillOpacity": 0.6, "values": [...]}
```

两处位置不一致，小一照着写会困惑。

**建议**：**统一放 `style` 内**（`style` 是所有视觉属性的唯一容器），顶层只保留 `name / type / values / style / markers / subplot` 这些结构字段。示例同步改回：

```json
{"name": "fast_up", "type": "area", "values": [...], "style": {"fillOpacity": 0.6}}
```

## 附-2：markers 挂载点需覆盖 K 线主图

**问题**：当前 markers 是 `POST /api/indicator` 的字段，只能挂在**指标系列**上。但「BBJudge argmax 状态 ≠ 硬编码状态 的 bar 标红」最直观的位置是 **K 线蜡烛图主图**（`candlestick.setMarkers()` 的 aboveBar/belowBar）。

**现状绕法**：造一个 dummy indicator（如 `type:"line"`, `values:全 null`）来承载 markers，再画在副图上。

**建议**（二选一，小一实现时定）：
- 方案 A：`POST /api/ohlcv` 也支持 `markers` 字段，直接标在主图 K 线上；
- 方案 B：保持 markers 只挂 indicator，但文档注明「主图标记通过挂一个空值 indicator 到 main 实现」。

> 倾向 A（更自然），但 B 也能用，不阻塞。

## 附-3：堆叠面积图的 cumsum 责任方未约定

**问题**：5 态概率要堆叠成「总面积 = 1」，需要把概率做**累积和（cumsum）**再画 5 条 area。但 PRD 没约定 cumsum 是脚本端算还是前端自动堆。

**建议**：**脚本端算 cumsum**（保持前端只做「画」不做「算」）：

```python
# 脚本端：5 态概率 → 5 条累积面积
def stack_probs(prob_rows):
    # prob_rows: [{fast_up:.., slow_up:.., ranging:.., slow_down:.., fast_down:..}, ...]
    import numpy as np
    order = ["fast_up", "slow_up", "ranging", "slow_down", "fast_down"]
    # 每根累积，返回 5 条数组（第 i 条 = 前 i 态概率之和）
    ...
```

- 脚本端输出 5 条 area 的**累积值**（非原始概率）；
- 前端按 `type:"area"` 直接画，不做任何堆叠逻辑；
- 最底层 area 的 `bottomColor` 用透明，其余正常。

> 这样前端零堆叠逻辑，脚本端完全掌控堆叠顺序和语义。

---

## 给小一的复审邀请

以上「附录 3 点」是框架已定之后的实现细节。请小一基于 v1.5 PRD 通读一遍，**重点确认**：

1. 后端 API 结构（`lines` 多线、`markers`、`style` 扩展）是否与 Lightweight Charts v5 的 series/primitive API 完全对得上，有没有遗漏的视觉属性（如 area 的 `lineWidth`、candlestick 的 `wickColor/upColor/downColor` 等）；
2. 附录 3 点你倾向哪种实现（附-2 选 A 还是 B）；
3. 有没有我们（量化使用者）还没考虑到的其他需求。

确认后回贴，三方（小c / 小幺 / 小一）达成一致，即可开工。
