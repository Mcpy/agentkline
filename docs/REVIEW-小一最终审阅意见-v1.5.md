# 画板 PRD 最终审阅意见（小一）

> **审阅人**：小一（开发负责人，负责实现本 PRD）
> **审阅对象**：`PRD-交互式K线画板与实时行情.md` v1.5
> **审阅日期**：2026-08-25
> **审阅角度**：开发可行性 + API 完整性 + 实现细节对齐
> **前置审阅**：小c 审阅意见（v1.4.1）已通过

---

## 一、总体结论

**架构方向正确，可以开工。** 需修正 3 个文档级问题（补表格/加说明），不改架构。

---

## 二、确认保留不动的设计 ✅

| 设计 | 评价 |
|------|------|
| 多画板 + 多时间周期层级 | 正确，数据隔离清晰 |
| 全脚本化数据源 | 核心亮点，灵活性极高 |
| `?board_id=xxx&timeframe=xxx` 显式指定 | AI 自动化的关键设计 |
| 渐进式沙箱 L1→L4 | 务实 |
| WebSocket 推送（不刷新页面） | 正确 |
| 内存存储（v0.1） | 调试工具够用 |
| series 类型扩展 + markers | 满足 BBJudge 场景 |
| NaN → null 后端强制处理 | 正确，前端不该处理这个 |
| values 与 K 线索引对齐（等长+null占位） | 清晰 |
| 多线模式（lines 数组，每条独立 type） | 解决 MACD 混合类型问题 |

---

## 三、开发前需修正（3个）

### 修正1: API 表格（5.1节）遗漏数据源相关端点

**问题：** 以下端点在 3.3 节文字中提到了，但 5.1 节 API 表格里没有。

**需补充的端点：**

| 方法 | 路径 | 用途 |
|------|------|------|
| `POST` | `/api/board/{id}/timeframe/{tf}/datasource` | 配置数据源（静态/轮询） |
| `DELETE` | `/api/board/{id}/timeframe/{tf}/datasource` | 停止数据源 |
| `GET` | `/api/board/{id}/timeframe/{tf}/datasource` | 查看当前数据源状态 |
| `POST` | `/api/board/{id}/timeframe/{tf}/refresh` | 手动刷新（重拉K线+重算指标） |
| `POST` | `/api/indicator/refresh/{name}` | 手动重算单个指标 |
| `POST` | `/api/markers` | 更新K线主图标记（见修正4） |

**动作：** 补进 5.1 节 API 表格 + 补每个端点的详细规格（请求体/响应体）。

---

### 修正2: WebSocket 消息表格（5.2节）遗漏

**问题：** 以下消息在 3.3 节和变更记录中提到了，但 5.2 节消息表格没有。

**需补充的消息：**

| 消息类型 | 用途 | 数据格式 |
|---------|------|----------|
| `datasource_start` | 数据源启动（含轮询配置） | `{type, board_id, timeframe, poll_interval}` |
| `datasource_stop` | 数据源停止 | `{type, board_id, timeframe}` |
| `datasource_error` | 数据源报错（3次失败） | `{type, board_id, timeframe, error, retry_after}` |
| `indicator_refresh` | 指标自动重算完成 | `{type, board_id, timeframe, name, values, subplot}` |

**动作：** 补进 5.2 节消息表格。

---

### 修正3: `run-script` 与 `datasource` 关系需明确

**问题：** 两个 API 都能"跑脚本拿 K 线"，功能重叠，文档没解释关系。

**需在 5.1 节或 3.3 节加一段说明：**

```
## run-script 与 datasource 的关系

| API | 用途 | 区别 |
|-----|------|------|
| `POST /api/run-script` + `save_as:"ohlcv"` | 一次性跑脚本拿数据 | 通用接口，不支持轮询 |
| `POST /api/board/{id}/timeframe/{tf}/datasource`（不传 poll_interval） | 一次性跑脚本拿数据 | 语义更清晰，挂在具体画板+时间周期上 |
| `POST /api/board/{id}/timeframe/{tf}/datasource`（传 poll_interval） | 持续轮询 | 实时数据源，仅此 API 支持 |

推荐：
- 一次性加载数据 → 用 `datasource`（语义清晰）
- 实时轮询 → 必须用 `datasource`（run-script 不支持）
- `run-script` 保留为通用入口（向后兼容）
```

**动作：** 加说明段，不改架构。

---

### 修正4: 补充 `POST /api/markers` 端点

**问题：** 小c 附-2 提出"markers 需要能挂到 K 线主图"。我决定采用方案 A（见第五节）。

**需新增的端点：**

```http
POST /api/markers?board_id=btc&timeframe=1d
Content-Type: application/json

{
  "markers": [
    {
      "time": 1714521600000,
      "position": "aboveBar",
      "color": "#ef5350",
      "shape": "circle",
      "text": "状态不一致"
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

**行为：**
- 覆盖当前 K 线主图的所有 markers（全量替换，非追加）
- 清空用空数组 `{"markers": []}`
- WebSocket 推送 `markers_update` 消息

**动作：** 加进 5.1 表格 + 详细规格 + 5.2 加 `markers_update` 消息。

---

## 四、开发期实现决定（不需要改 PRD，我直接执行）

| # | 决定 | 理由 |
|:---:|------|------|
| 1 | K 线蜡烛图样式硬编码默认值（涨绿跌红） | v0.1 不做自定义样式 |
| 2 | 切换画板/时间周期时重置视口（显示全部数据） | 不同画板数据范围不同，保留视口会空白 |
| 3 | 前端状态栏显示脚本执行进度（>10s提示） | 用户体验，不做后端超时 |
| 4 | 前端单文件 `static/board.html` | 内部工具，不需要构建系统 |
| 5 | Lightweight Charts 用本地文件（不用 CDN） | 内网可能无外网 |
| 6 | 同名指标再次提交默认覆盖（等同 `replace: true`） | 调参是最高频操作，不应报"已存在" |

**决定6 特别说明：**

```
当前 PRD 行为：同名指标 → 报错
我的实现：同名指标 → 直接覆盖（更新 values/style/subplot）
         WebSocket 推送 `indicator_update`（而非 indicator_add）
```

需在 5.2 消息表格补一个 `indicator_update` 消息：

| 消息类型 | 用途 | 数据格式 |
|---------|------|----------|
| `indicator_update` | 同名指标覆盖更新 | `{type, board_id, timeframe, name, values, subplot, style}` |

---

## 五、对小c 3 个实现细节的决定

### 附-1: fillOpacity 位置 → 统一放 `style` 内

```json
// ✅ 正确
{"name": "fast_up", "type": "area", "values": [...], "style": {"fillOpacity": 0.6}}

// ❌ 错误（当前 PRD BBJudge 示例中的写法）
{"name": "fast_up", "type": "area", "fillOpacity": 0.6, "values": [...]}
```

**动作：** 修正 PRD 中 BBJudge 典型场景的 JSON 示例（把 `fillOpacity` 移入 `style`）。

### 附-2: markers 挂载点 → 方案 A（K 线直接支持 markers）

**决定：**
- `POST /api/ohlcv` 支持可选 `markers` 字段（随 K 线一起推）
- 新增 `POST /api/markers` 独立端点（单独更新主图 markers）
- 指标系列上的 `markers` 字段保留（已有设计不动）

**理由：** "在 K 线上标记状态不一致"是最高频场景，不应绕道创建空值 indicator。

### 附-3: 堆叠面积图 cumsum → 脚本端算

**决定：** 脚本端负责累积值计算，前端只画不算。

**动作：** 在附录 A（Python 指标脚本约定）末尾补充：

```
### 堆叠面积图约定

堆叠面积图场景（如 5 态概率堆叠）：
- 脚本端负责计算累积值（cumsum），输出 5 条面积图的**累积数组**
- 前端按 `type:"area"` 直接画，不做任何堆叠逻辑
- 堆叠顺序由脚本端控制（lines 数组顺序 = 从底到顶）
- 最底层 area 建议 `style.bottomColor` 用透明

示例：
  原始概率: fast_up=0.3, slow_up=0.2, ranging=0.4, ...
  累积值:   line1=0.3, line2=0.5, line3=0.9, ...
  前端画 5 条 area，自动形成堆叠效果
```

---

## 六、补充建议（可选，不阻塞开工）

| # | 建议 | 优先级 | 说明 |
|:---:|------|:---:|------|
| 1 | `GET /api/state` 返回加 `meta` 字段 | 低 | 含创建时间/最后更新时间/数据量 |
| 2 | 前端日志面板加"复制"按钮 | 低 | 一键复制，方便反馈 |
| 3 | 画板 Tab 标题显示 symbol + interval | 低 | "BTCUSDT 1d" 而非仅 "btc" |
| 4 | 同名指标覆盖（已在第四节决定） | 已定 | 调参高频操作 |

---

## 七、给小幺的修改清单

| # | 修改项 | 位置 | 动作 |
|:---:|--------|------|------|
| 1 | 补 6 个 API 端点到 5.1 表格 | 5.1节 | 加表格行 + 详细规格 |
| 2 | 补 5 个 WebSocket 消息到 5.2 表格 | 5.2节 | 加表格行 |
| 3 | 加 `run-script` 与 `datasource` 关系说明 | 3.3节或5.1节 | 加一段文字 |
| 4 | 新增 `POST /api/markers` 详细规格 | 5.1节 | 加完整规格 |
| 5 | 修正 BBJudge 示例 JSON（fillOpacity 移入 style） | BO-5.1 示例 | 改 JSON |
| 6 | 附录 A 补堆叠面积图约定 | 附录A末尾 | 加一段 |
| 7 | 新增 `indicator_update` WebSocket 消息 | 5.2节 | 加表格行 |

**修改量估计：** 约 100-150 行新增/修改。不改架构，不改已有 API 结构。

---

## 八、最终结论

| 项目 | 状态 |
|------|:---:|
| 架构设计 | ✅ 通过 |
| API 设计 | ⚠️ 需补遗漏（修正1-4） |
| WebSocket 消息 | ⚠️ 需补遗漏（修正2） |
| 小c 3 个实现细节 | ✅ 已决定 |
| 开发可行性 | ✅ 无技术障碍 |
| 预计开发量 | 后端 ~800行 + 前端 ~2000行 |

**小幺改完表格后回复，我确认即可开工。**
