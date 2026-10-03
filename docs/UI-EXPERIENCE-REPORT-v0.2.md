# AgentKline 初版体验报告 (v0.2)

> **体验时间**：2026-08-26
> **体验人**：小幺
> **版本**：agentkline v0.2.0（基于 PRD v1.6）
> **服务地址**：http://localhost:8765

---

## 一、体验结论

### ✅ 已实现核心功能（小一完成得很好）

| 功能 | 状态 | 备注 |
|------|------|------|
| 多画板 + 多时间周期 API | ✅ | POST /api/board 正常 |
| K 线数据加载（脚本执行）| ✅ | /api/run-script 完美 |
| 副图管理（MACD / RSI / VOL）| ✅ | 自动布局正常 |
| 指标（主图 + 副图）| ✅ | SMA / MACD / RSI 全跑通 |
| e2e 测试 | ✅ | 22/22 passed |
| MCP server | ✅ | 17 个工具 |
| 打包 | ✅ | pyproject.toml + setuptools |

### ⚠️ 发现的问题

1. **同名指标被覆盖**：`sma(20)` 和 `sma(60)` 都是 `name="sma"`，第二个覆盖第一个
   - v1.6 PRD 说"同名指标默认覆盖"，但**没让用户指定不同名字**
   - 修复方案：API 应该接受 `indicator_name` 字段（PRD v1.6 没写清楚）

2. **VOL 副图自动创建** —— 这是小一的贴心默认，但 PRD 没明说

---

## 二、UI 现状分析（小幺截图）

### 现状
- **顶部**：单行状态栏（画板 + 周期 + 指标计数）
- **主图**：全屏 K 线 + 网格
- **副图**：自动堆叠（VOL → MACD → RSI）
- **底部**：可折叠日志面板（▲ 收起）

### 与 TinySign / TradingView 的差距
- ✅ **CSS OK**：基础布局、颜色、K 线渲染都正常
- ⚠️ **JS 交互缺失**：Tab 切换 / 工具栏按钮 / 快捷键 / 拖动调整高度
- ⚠️ **视觉细节简陋**：
  - 状态栏只是文字，没有图标 + 颜色徽章
  - 指标图例没有颜色块（无法区分 sma(20) vs sma(60)）
  - 副图标题没有"展开/收起"按钮

---

## 三、UI 改进建议（8 条，按性价比排序）

### 🟢 立即可做（1-2 小时，性价比最高）

1. **顶部状态栏 → 工具栏重设计**
   - 借鉴 TradingView symbol 选择器 + 周期选择器布局

2. **指标图例加颜色块 + 可见性切换按钮**
   - 每个指标前一个颜色方块（与图上颜色一致）

3. **副图标题加"展开/收起/删除"按钮**
   - 借鉴 v1.6 PRD BO-7 的设计

4. **工具栏按钮（圆角药丸状）**
   - 借鉴 TinySign `.btn-primary` 样式（#2962FF + border-radius: 80px）

### 🟡 中等投入（半天）

5. **主题切换（Dark/Light switcher）**
   - 借鉴 TinySign 的 switcher 组件

6. **数据状态徽章（彩色 Status Badge）**
   - 🟢 数据实时 / 🟡 数据延迟 / 🔴 断开

### 🔴 大投入（1-2 天，留 v0.2/v1.5）

7. **拖动调整副图高度**
8. **画线工具 / 快捷键 / 右键菜单**

---

## 四、推荐

**做 1-6（半天）**，效果从"Intern 模式"提升到"Junior Pro 模式"。

**跳过 7-8**（v0.1 不影响验收，v0.2/v1.5 再做）

---

## 五、截图存档

截图位于 `docs/screenshots/` 子目录：

- `docs/screenshots/01-initial-empty-state.png` - 初始空状态
- `docs/screenshots/02-with-btc-data.png` - 加载 365 根 K 线后
- `docs/screenshots/03-full-view-indicators.png` - 完整视图（3 个指标 + 3 个副图）

---

## 六、原始测试命令

```bash
# 创建画板
curl -X POST http://localhost:8765/api/board \
  -H "Content-Type: application/json" \
  -d '{"id": "btc", "name": "BTC 1Y 1d", "symbol": "BTCUSDT", "intervals": ["1d"]}'

# 加载 K 线（用 mock 脚本）
curl -X POST "http://localhost:8765/api/run-script?board_id=btc&timeframe=1d" \
  -H "Content-Type: application/json" \
  -d '{"path": "/mnt/Projects/agentkline/scripts/mock_btc_data.py", "func": "main", "save_as": "ohlcv", "params": {"days": 365}}'

# 添加 SMA 20 指标
curl -X POST "http://localhost:8765/api/run-script?board_id=btc&timeframe=1d" \
  -H "Content-Type: application/json" \
  -d '{"path": "/mnt/Projects/agentkline/scripts/sma.py", "func": "main", "save_as": "indicator", "params": {"period": 20}, "indicator_name": "SMA20"}'

# 添加 MACD 副图指标
curl -X POST "http://localhost:8765/api/run-script?board_id=btc&timeframe=1d" \
  -H "Content-Type: application/json" \
  -d '{"path": "/mnt/Projects/agentkline/scripts/macd.py", "func": "main", "save_as": "indicator", "subplot": "MACD", "params": {"fast": 12, "slow": 26, "signal": 9}, "indicator_name": "MACD"}'

# 添加 RSI 副图指标
curl -X POST "http://localhost:8765/api/run-script?board_id=btc&timeframe=1d" \
  -H "Content-Type: application/json" \
  -d '{"path": "/mnt/Projects/agentkline/scripts/rsi.py", "func": "main", "save_as": "indicator", "subplot": "RSI", "params": {"period": 14}, "indicator_name": "RSI"}'
```

---

## 七、下一步

| 选项 | 行动 |
|------|------|
| A | **立即做 1-6（半天 UI 改进）** |
| B | **保持现状，专注后端完善** |
| C | **小幺写一份详细的 UI 设计规范（UI-DESIGN.md）**，按规范实施 |
| D | **小一继续完善后端细节**（先小幺在 PRD 里补 indicator_name 字段说明） |
