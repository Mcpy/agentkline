# Vela 内部耦合与升级门（v0.5.4）

> **定位**：薄适配层公开 API 之外的「内部面」台账。升级 Vela 前先读这一页，十分钟知道哪里会断、怎么回归。
> **当前基线**：Vela 0.8.4，`frontend/vendor/assets/vela.global.min.js`，sha256 `4071c32b8cb65e5b75eefb5a6973babc1a90b3f875e44b7d5dad32be181a606f`。
> **唯一接触点**：`frontend/src/vela_adapter.js`。应用层不直接摸 `window.Vela`，新增内部面也只能加在这里。

## 1. 为什么会有内部耦合

Vela 的公开 API 已覆盖图表、指标、画线、标记、事件和截图，正常功能全部走公开面。但有两类能力没有公开出口：

1. **最新价越界贴边**：原生 `drawPriceLineAndCountdown` 在最新价 y 超出 price pane 时直接 `return`，标签和倒计时一起消失；公开 API 不提供「贴顶/贴底」钩子。
2. **价格轴几何与颜色**：需要读 price pane 的 `scale/bounds`、`percentBaseline`，以及当前价格元素颜色；这些只在 renderer 内部的 `scene/coords/chrome` 上。

处理原则：**不改 vendor、不 fork**，在适配层包一层；能降级就降级，绝不让内部接口异常冒到渲染循环。代价是这些内部面要进升级回归。

## 2. 内部面清单

| 位置 | 用途 | 失效表现 | 兜底 | 回归 |
|---|---|---|---|---|
| `chart.orchestrator.renderer` | 进入 renderer 的唯一入口 | 贴边标签不出现 | try/catch，退回纯原生 | UI smoke #6 |
| `renderer.chrome.drawPriceLineAndCountdown` | 包一层，原生画完后补越界块 | 补丁不生效，越界仍无标签 | wrapper try/catch，不影响原生绘制 | UI smoke #6 |
| `renderer.chrome.priceElementColor` | 取当前价格元素色（K 线/线/面积） | 颜色退回涨跌色 | `theme.upColor/downColor` | UI smoke #6 |
| `renderer.scheduler.invalidate(4)` | 绑定后立即触发一次重绘 | 首帧可能等到下一次重绘才出现 | 无（只影响首帧延迟） | 人工/截图 |
| `renderer.scene.bars` | 取最新 bar 的 close | 贴边块不出现或价格旧 | 无，直接不画 | UI smoke #6 |
| `renderer.scene.panes` | 找 `kind === 'price'` 的 pane | 找不到 pane → 不画 | 遍历 Map/对象的两种形态 | UI smoke #6 |
| `renderer.scene.showPriceLabel` | 跟随原生「Last Price Label」开关 | 用户关掉标签后仍出现贴边块 | 显式 `false` 才隐藏 | 人工设置 |
| `renderer.scene.candlesHidden` | 隐藏 K 线时原生不画标签 | 隐藏 K 线后仍出现贴边块 | 跟随原生隐藏 | 人工 |
| `renderer.scene.scaleMode` | 判断 price/percent/indexed | 百分比轴显示原始价格 | 按 percent/indexed 格式化 | UI smoke 扩展/人工 |
| `pricePane.scale`（min/max/invert/log） | 判断越界方向、倒置轴贴哪边 | 上下贴反或误判越界 | 无法兜底，直接不画 | UI smoke #6 |
| `pricePane.bounds`（top/height） | 贴顶/贴底的像素位置 | 标签错位 | 无法兜底，直接不画 | UI smoke #6 |
| `pricePane.percentBaseline` | percent/indexed 的基线 | 百分比文本错误 | 基线无效时退回价格文本 | 人工 |
| `pricePane.collapsed` | 折叠 pane 时不画 | 折叠后仍出现块 | 跟随原生跳过 | 人工 |
| `coords.devicePixelRatio` | 轴宽 = canvas 宽 / dpr − dataW | 块过宽/过窄 | 轴宽兜底 64px | UI smoke #6 |
| `pane.heightWeight` | 布局权重（PoC 验证的旋钮，非公开文档面） | pane 高度不适配 | 保持默认高度 | 人工布局检查 |
| `#main-chart` 内 legend 行（文字 `VRVP` 的 span→row div） | VPVR 图例行隐藏：保留 DOM（设置面板仍能定位）只把该行 `display:none`；MutationObserver 防 Vela 重建 | 图例重新出现（行可见） | 结构变了就不再隐藏，chip/设置仍可用 | UI smoke #5 |
| `handle.nativeType` / `pane.indicators` | 识别 volume/subplot 组 | volume 不移位、显隐/组挂载异常 | 回退到 title 判断 | e2e + 视觉 |
| `renderer.onCrosshairMove` | 十字线通道：OHLC 行读数 + 0.6.2 交易点点击命中 | 十字线不更新、OHLC 停在旧值、点交易点无反应 | 无；OHLC 回落到最新一根，点击不命中（不报错） | UI smoke #10 + 人工 |
| emit 载荷「隐藏 series 对 + fills + polyline」（结果层交易盒） | 0.6.2 B2：Vela 没有 time×price 矩形的通用图元（`boxes` 只服务表格）；用 `visible:false` 的常值 series 对（持仓段=进/出价格，段外 `{time,value:null}`）+ `fills` 逐段填充，视觉上就是买点↔卖点对角矩形。按「多/空 × 选中/未选中」发 4 对（8 条隐藏 series + 4 条 fill）：选中 0.16、其余 0.06；选中盒子另发一条 `closed:true` 的 polyline 描边（fill 图元没有 stroke，只能靠折线画四边）。**隐藏 series 仍会被 fills 的 id 查找解析到**（这是该方案成立的前提） | 交易盒/描边不出现、或选中样式不生效 | 无（去掉 series 对即退回纯标记） | UI smoke #11 |
| emit 载荷 `fills` + 双 series（结果层水下填充） | 0.6.2 B2：净值与高水位两条 series 之间填充；HWM 必须是每根 bar 一个 `{time,value}` 点，**窗口外也要给 `value:null` 的对象**（给裸 `null` 会在 `history:complete` 触发 Vela `applyModel` 读 `time` 崩溃） | 水下填充消失 / 回补历史时 console 报 `Cannot read properties of null (reading 'time')` | 无（去掉 HWM/fill 即退回单条净值线） | UI smoke #11 |

公开面（升级时按普通回归即可）：`chart.indicators()`、`chart.panes.list()/move()`、`chart.drawings`、`chart.marks`、`chart.on()`、`chart.renderer.set()`、`chart.renderer.screenshot()`、`chart.setVisibleRange()` 等。

> VPVR 图层（v0.5.4）走公开 `chart.addNativeIndicator('vpvr')`；图例行隐藏是唯一额外耦合（内置 descriptor 未开 `legend:false`，
> 而设置面板依赖 legend 行，故保留 DOM 只隐藏行）。UI smoke #5 覆盖开关、图例隐藏、OHLC 对齐、设置入口、刷新恢复与参数保留。

## 3. 升级门（按顺序全绿才换版本）

1. **换 bundle**：替换 `frontend/vendor/assets/vela.global.min.js` 与同名 `.sha256`，`cd frontend && npm run build`。
2. **PoC/回归页**：
   ```bash
   cd tools/vela-regression
   python -m http.server 8799 &
   python runner.py p1 p2 p3 p4 p5 p6 p7 p8 p9 p10
   ```
   全绿=公开面与已知内部面没断；红=先修 `vela_adapter.js`，修不绿回退版本。`p11.html` 是实验页，不在门内。
3. **UI 冒烟（本单新增）**：
   ```bash
   uv pip install -e ".[dev]"          # 或 pip install -e ".[dev]"
   python -m playwright install chromium   # 已有 Chrome 可设 AK_CHROMIUM
   python tools/ui_smoke.py
   ```
   11 条全绿：指标库打开/搜索、加实例、收藏刷新、最近使用顺序、VPVR 图层开关（含参数保留）、越界贴边、
   指标对齐、+回测、定位历史、0.6.2 B1 的「点行/口径/图上点选」、0.6.2 B2 的「水下 + 持仓带」。
4. **API e2e**：临时实例上 `python test_e2e.py --port 18766`，196/196。
5. **人工**：打开 live，拖动价格轴让最新价越界 → 顶部/底部出现 `▲/▼`；恢复区间 → 原生标签回来且无重复；指标库收藏/最近使用正常。
6. **更新本页**：内部面有增删/改名时同步改表，并在 UI smoke 或 regression 里补对应用例。

## 4. 越界贴边的实现要点

- 原生逻辑：`if (y < pane.top || y > pane.top + height) return;` —— 标签、虚线、倒计时一起跳过。
- 适配层：`orig.call(...)` 后再判断 `last.close` 是否落在 `scale.min..scale.max` 外：
  - 高于区间 → 贴 pane 顶部，`▲`；
  - 低于区间 → 贴 pane 底部，`▼`；
  - 倒置轴时贴边方向随 `scale.invert` 反转，箭头仍表示价格方向。
- 文本格式对齐原生：常规轴按刻度密度定小数；宽对数轴按量级；percent/indexed 按基线换算。
- 颜色取 `priceElementColor`，文字用 `tagTextColor` 同式对比色；轴宽按 `canvas/dpr - dataW`，放不下时逐级缩字号。
- 画在 **chrome canvas** 上，所以 `renderer.screenshot()`、快照、MCP 截图都会带上；不是 DOM 浮层，也不需要事件轮询——每次原生重绘自动跟随（拖动价格轴、缩放、tick、resize 都覆盖）。
- 区间内完全不动原生标签，所以不会出现双标签。`showPriceLabel === false`、K 线隐藏、pane 折叠、无 bar 时直接不画。

## 5. 新增内部面的纪律

1. 先找公开 API；找不到才用内部面。
2. 只允许写在 `vela_adapter.js`，且必须 `try/catch` + 可降级；异常不能进入渲染循环。
3. 同步更新本页表格 + 至少一条回归（UI smoke 或 regression 页）。
4. 禁止手改 `vela.global.min.js`；版本升级走「换 bundle + 回归」，不 fork。

## 6. 交易点点击（0.6.2 B1，B2-fix 改为交易盒内命中）

- 事实：结果交易点用的是 **labels**（`abovebar/belowbar` 点形状 + B/S 文本），Vela 没有 labels 的点击回调；`chart.on()` 也没有 label 事件。
- 方案：**十字线时间 + 十字线价格 + 容器 click** 命中——`renderer.onCrosshairMove` 记录 `ohlc.time` 与 `price`（仅 `paneKind === 'price'`），在 `#main-chart` 捕获 click，交给 `results.onChartBarClick(ms, price)`。
- 命中规则（优先级从高到低）：
  1. **B/S 标记 ±6px 圆形**：标记中心 = `priceToY(bar.high/low) ∓ 14px`（与 Vela label 绘制公式一致，`abovebar` 上移 14、`belowbar` 下移 14），x = `coords.timeToX`；只对屏幕内（`0 ≤ x ≤ widthPx`、`0 ≤ y ≤ pane 高`）的标记生效。
  2. **交易盒内**：`entry_time ≤ ms ≤ exit_time` 且 `price ∈ [min(entry_price, exit_price), max(...)]`，与图上矩形完全一致；盒外不再误触。嵌套/重叠取时长最短的一笔。
- 坐标换算的坑：画布原点 ≠ `#main-chart` 原点（左侧画线工具栏占一条 gutter，约 44px），必须用「与 `coords.widthPx` 最接近的那个 canvas」的 `getBoundingClientRect()` 做偏移，否则整体偏一条工具栏。
- 降级：十字线通道失效时不报错，只是点盒子没反应；明细表点行仍可定位（`focusTradeRange`）。**注意**：点击其它 pane（成交量/净值）时 `price` 为 null，不走盒命中，按“空白”处理。
- 边界：多结果同屏只命中**当前激活**结果；盒子的价格上下沿就是成交价，不含持仓期间的最大浮盈/浮亏。
- 拖拽与单击分离：`pointerdown` 记起点，`pointermove` 超过 4px 标脏，只有「在 canvas 上原地按下即松开、且 <700ms」才当作点击；拖拽平移/长按不会误清选中，点工具栏等 DOM 也不触发。
- 选中态刷新：切换选中**不能**走 `refreshResultLayer()`——它会 `remountGroup(RES)` 重建净值/HWM/水下填充并重排 pane，点击有百毫秒级延迟；改用 `refreshResultMarksOnly()`（`reEmit(RES_MARK)` + `renderer.scheduler.invalidate(4)`），实测 5–10ms，描边/填充立刻更新。点空白（不在标记也不在盒子内）取消选中，走同一条轻量路径。
- 回归：UI smoke #10 接线（`__akClickCalls`）+ 盒内点选 + 盒外不误选；#11 水下/交易盒/描边（8 条隐藏 series + 4 条 fill + 1 条 polyline）；#12 点空白取消选中。标记命中另有调试钩子 `__akMarkerPoints()` / `__akHitTest(x,y)` / `__akMarkerHits`（视口相关，冒烟只断言接线与盒命中，标记用钩子人工核）。
