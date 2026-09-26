---
name: ai-walkthrough
description: AI 引导呈现流程（v0.4）——把分析结论（标记/划线）自动带到用户屏幕：set_markers/add_drawing → switch_board/switch_timeframe → set_view_range；含板锁语义（现场=锁定画板、SOURCE_LOCKED 跟 suggestion 改道）、省 token 读取与 get_current_view。
---

# AgentKline AI 引导呈现（v0.4 skill）

让 AI 把"回测亏损归因 / 信号解读"等结论**自动呈现**到用户眼前，无需人工翻找。

## 0. 现场语义（v0.4 一标的一板）
- 画板 = 某标的的分析**现场**：`source_lock={script, identity快照}`，建板即锁、不可变。
- 你的分析要落在**对应标的的现场**里：先 `list_boards`/`overview` 找现成现场；
  没有就 `create_board(symbol=..., source=..., params=...)` 建板即锁，或空板（仅 AI 可建）+ `set_kline_source` 首配锁。
- 撞锁 `SOURCE_LOCKED`（409）= 你想往别的标的现场塞内容：**跟 `suggestion` 一键改道**
  （suggestion.action=create_board 带全要素），不要重试原板。
- 标记/划线/指标实例都锚定现场坐标系：与现场共存亡，不归档不克隆。

## 1. 标准顺序（先落内容，再切视图，最后聚焦）
1. `set_markers(board, tf, markers)` —— 落买卖点/事件标记；
   越界 time 会被丢弃并在返回 `dropped` 中回报，可自我纠正。
2. `add_drawing(board, tf, type, points)` —— 画趋势线/水平线（hline/trend）。
3. `switch_board(board)` / `switch_timeframe(tf)` —— 把前端切到目标板/周期
   （switch 广播窗口化状态≤2000 根，标记/划线随之呈现；更老历史用户左滚按需 backfill）。
4. `set_view_range(board, tf, from, to)` —— 画面聚焦到目标时间段（如回撤区间）。

## 2. 读用户视图
- `get_current_view()` —— 返回用户**真实**在看的 board/timeframe/可见时间窗
  （前端防抖 500ms 上报）。用于"解释我当前看的这段"等上下文感知场景。
- `set_view_range` 写入的 current_view 服务端同步生效，随后 `get_kline()`/
  `get_indicators()` 不传范围即对齐该窗口，**不会拿到旧数据**。

## 3. 省 token 读取
- `overview`（仅结构：source_lock/槽状态/指标实例元信息/计数）→ 先看有什么；
- `get_kline`（K线+成交量）/ `get_indicators(instances=...)`（按 inst_id 过滤）按需取数；
- 指标实例把手是 inst_id（recipe=随K线重算 / blob=冻结）；改参数用 `update_indicator(inst_id, params=...)`。
- 不要对大画板直接全量拉取。

## 4. 验证
- `take_snapshot()` 返回 image 块，多模态模型可直接读图确认呈现效果。
- 截图反映响应 snapshot_request 的浏览器当前视图；无浏览器在线时不会回退旧图（报 NO_BROWSER 姿态）。


## 雷达与性能意识（v0.4.1）
- 盯盘用 watchlist_add/list + get_quotes；行三态 visible/hidden/watch 解读用户注意力；
- 读 `eff_poll_s` 判断槽当前轮询档；非可见槽数据允许分钟级旧——讲解时切即补拉已兜底；
- 大批量盯盘同源只占一次批量请求，放心加行。
