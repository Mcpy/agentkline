---
name: ai-walkthrough
description: AI 引导呈现流程——把分析结论（标记/划线）自动带到用户屏幕：set_markers/add_drawing → switch_board/switch_timeframe → set_view_range，及读取用户视图 get_current_view。
---

# AgentKline AI 引导呈现（skill）

让 AI 把"回测亏损归因 / 信号解读"等结论**自动呈现**到用户眼前，无需人工翻找。

## 标准顺序（先落内容，再切视图，最后聚焦）
1. `set_markers(board, tf, markers)` —— 落买卖点/事件标记；
   越界 time 会被丢弃并在返回 `dropped` 中回报，可自我纠正。
2. `add_drawing(board, tf, type, points)` —— 画趋势线/水平线（hline/trend）。
3. `switch_board(board)` / `switch_timeframe(tf)` —— 把前端切到目标板/周期
   （switch 会广播完整状态，标记/划线随之呈现）。
4. `set_view_range(board, tf, from, to)` —— 画面聚焦到目标时间段（如回撤区间）。

## 读用户视图
- `get_current_view()` —— 返回用户**真实**在看的 board/timeframe/可见时间窗
  （前端防抖 500ms 上报）。用于"解释我当前看的这段"等上下文感知场景。
- `set_view_range` 写入的 current_view 服务端同步生效，随后 `get_kline()`/
  `get_indicators()` 不传范围即对齐该窗口，**不会拿到旧数据**。

## 省 token 读取
- `overview`（仅结构）→ 先看有什么；
- `get_kline`（K线+成交量）/ `get_indicators(names=...)`（可过滤）按需取数；
- 不要对大画板直接全量拉取。

## 验证
- `take_snapshot()` 返回 image 块，多模态模型可直接读图确认呈现效果。
