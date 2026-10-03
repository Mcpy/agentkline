# Vela PoC 实验单（写码会话任务书）

> **性质**：决策门验证任务书。PoC 六点是**唯一决策门**（2026-10-01 用户裁定）——全绿才换 Vela 进行 0.5；任何硬伤=整包回退（版本重排撤销）。**失败也是产出，如实记录，禁止美化**。
> **依据**：`ARCH_DISCUSSION_v0.5.md` §7（PoC 六点）。本单只管"怎么验"，不预设结论。
> **交付**：逐点实验页+证据存档+总产出矩阵，见 §9。

---

## 0. 环境准备

- **PoC 独立目录**：`/mnt/Projects/agentkline/poc-vela/`——**严禁改动主项目任何代码**（frontend/src、web_dist 等一律不碰）；
- **Vela 获取**：优先**浏览器 bundle 路径**（`vela.global.min.js` + `vela.global.js`，从 npm 包 `@luxalgo/vela` 或 GitHub Releases 取 dist），script 标签引入——P5 本来就要验这条路径；备选 npm 路径仅作对照；
- **版本纪律**：记录确切版本号（package.json version / 文件 hash）到 `poc-vela/VERSION.md`——官方明说 API 未稳，**结果绑定版本**；
- **禁止**：安装 `@luxalgo/vela-pinets` 或 `pinets`（AGPL，许可纪律红线）；
- **实验页形态**：每点一个独立 HTML（`poc-vela/p1.html` … `p6.html`）+共享 `mock-data.js`；
- **验证方式**：浏览器打开实验页（或 Playwright/Puppeteer 自动化），每点截图+控制台输出存证到 `poc-vela/evidence/pN/`。

**mock 数据要求**（`mock-data.js`）：
- OHLCV：500 根日线随机游走（带趋势段+震荡段），`[{time, open, high, low, close, volume}]`（time=epoch 秒）；
- values 序列：equity 曲线（500 点，含回撤段）、双均线（fast/slow）、一条归一化对比线；
- 持仓区间：若干 `{from, to}` 段；交易点：若干 `{time, price, side, reason}`。

---

## P1 ⭐ 数据线/副图渲染（死穴——它不行，换底方案毙）

**验证需求**：后端算好的 values 画成"主图叠加线/独立副图"（0.4 指标呈现+0.6 equity 子图/持仓带/underwater 的共同地基）。
**疑虑**：API Reference 未直接露出"画任意时间序列"的 API（70+ 指标是内置计算、custom script 走引擎——咱们 values 直喂走哪条路？）。

**步骤**：
1. `p1.html` 起 Vela 图表（mock OHLCV 走 `data` 本地选项）；
2. 通读 `window.Vela` 公开面（Object.keys 递归打印到控制台存证）+GitHub docs（`docs/user/options.md`、`api-reference.md` 里 series/overlay/pane 相关）——**先找官方路径**；
3. 依次尝试三条路径，任一走通即记：
   - **路径 A**：原生 series/pane/overlay API（如 options 的自定义序列、addSeries、pane 管理）；
   - **路径 B**：`registerRendererLayer` 自定义渲染层（`render({bars,data,coords,scale,bounds})` 里用 coords/scale 把 values 映射成折线）；
   - **路径 C**：`registerChartType` 的 barTransform/dataEngine 通道；
4. 每条路径验证：叠加到主图（双均线）**和**独立副图（equity 曲线）两种形态；与 K 线**同轴缩放联动**（缩放/拖动时线跟着对齐）；
5. 加分项（记录可行与否即可）：多条线同副图（多结果对照）、半透明填充（underwater/持仓带的形态）。

**判据**：✅过=至少一条路径画出"给定时间序列"且同轴联动（主图+副图两种形态）；🟡部分=只能画主图不能副图（或反之）=记录 workaround；❌硬伤=三条路全不通。

---

## P2 数据流注入（架构符合度：后端不动）

**验证需求**：数据从后端来（WS 推送），Vela 不直连交易所。
**疑虑**：`deps.dataFeed` 的 MarketDataFeed 接口能否包住"历史分页加载+实时 bar 更新+多周期切换"。

**步骤**：
1. 查 `docs/user/data-providers.md`（MarketDataFeed port 的接口签名）；
2. `p2.html` 实现自定义 feed（mock）：`getBars` 分两批返回历史（模拟分页/慢加载）+`setInterval` 推送 forming bar 更新+新 bar 追加；
3. 从 `deps.dataFeed` 注入，**不注册任何 provider**；
4. 验证：首次加载（load:start→history:progress→load:end 事件时序）/实时更新（`bar` 事件）/`setMarket` 切换 symbol 与 timeframe/`market:changed` 事件；
5. 事件时序日志全量存证。

**判据**：✅过=历史+实时+切换三样全通，事件时序正确；🟡部分=某样受限（记录）；❌硬伤=接口根本包不住我们的数据形态。

---

## P3 画线程序化+持久化（AI 画线语义映射）

**验证需求**：`add_drawing`/`delete_drawing` MCP 语义→`drawings.add()`；drawings 白名单持久化→toJSON/fromJSON。
**步骤**：
1. `p3.html`：程序化创建各类型画线（hline/trendline/矩形/文字——以 `docs/user/drawing-tools.md` 类型目录为准，逐个试）；
2. 增删改查全套：`add/remove/update/lock/show/bringToFront`；
3. 事件核对：`drawing:created/edited/removed/selected` 是否齐；
4. **序列化往返**：`toJSON()`→清空→`fromJSON(doc)`→与原对象 diff（逐字段）；
5. `DrawingsDocument` 样例 JSON 存证（`evidence/p3/drawings-doc-sample.json`——持久化格式决策的原料）。

**判据**：✅过=类型够用（至少 hline+trendline+矩形）+增删改查+往返无损+事件齐；🟡部分=个别类型缺/个别字段丢（记录）；❌硬伤=程序化创建不可用或序列化不完整。

---

## P4 交易标记选型（reason 通道）

**验证需求**：交易点标记（带 reason 文本，点开看"为什么进"）+AI 划线族标记（set_markers）。
**步骤**：
1. `p4.html` 三方案实测：
   - **方案甲**：`marks.add()`——group=trades、glyph 买卖双色（circle/diamond）、`content: {panel: {items:[{type:'field',label:'reason',value:'...'}]}}`；截图点击弹窗；
   - **方案乙**：drawings 箭头/图标类工具画在 bar 上下；
   - **方案丙**：自定义渲染层画箭头+自绘弹窗；
2. 三方案对比记录：视觉效果（截图）/与 K 线 bar 的位置关系/程序化可控性/序列化支持/事件支持；
3. 附带验证 marks 的 group 聚簇（同 bar 多标折叠）与 `mark:click` 事件。

**判据**：✅过=三方案中至少一个满足"交易点+reason 可读可点"且选型定案（给推荐）；🟡=都可用但各有残（记录）；❌硬伤=无一满足。

---

## P5 浏览器 bundle 集成（工程形态）

**验证需求**：进原生 JS SPA（无构建链）。
**步骤**：
1. `p5.html`：模拟 web_dist 形态（原生 JS 模块+script 标签混用页），`<script src="vela.global.min.js">` 引入；
2. 起 Vela 图表与页面上模拟的"现有 UI 组件"（一个假的身份证卡 div+假雷达列表）共存；
3. 核对 `window.Vela` 的 API 覆盖度：P1 三条路径/P2 dataFeed/P3 drawings/P4 marks 所需 API 在 bundle 里是否都在（逐项打勾）；
4. 量体积：`vela.global.min.js` 文件大小记录（KB）；页面加载耗时粗测。

**判据**：✅过=图表正常+P1–P4 所需 API 全覆盖+体积可接受（软线 ≤2MB，超标记录数字再议）；🟡=个别 API 缺失（记录）；❌硬伤=bundle 功能阉割严重或无法与原生页共存。

---

## P6 架构边界断言（许可+零引擎依赖+workspace 评估）

**验证需求**：无 AGPL 沾染+values 直喂不经 scripting engine+workspace 用法建议。
**步骤**：
1. **零引擎断言**：P1–P4 的实验页全部**不注册任何引擎**（不调 registerEngine）——全功能正常即实证"不装 addon 零缺口"；
2. **依赖树检查**：bundle/npm 包的依赖里**不得**含 `pinets`/`@luxalgo/vela-pinets`（bundle 里 grep "AGPL"/"pinets" 字样存证）；
3. **workspace 评估**（轻量）：跑一下 workspace 的 quickstart demo（多图 layout:'4'+sync+persist），对照我们的 UI 需求（身份证卡/雷达/自选栏是我们的）写 200 字用法建议：headless core+ui kit 自建外壳 vs 借 workspace grid——推荐哪个。

**判据**：✅过=零引擎全功能+依赖树干净+建议成文；🟡=建议中发现疑点（记录）；❌硬伤=bundle 内嵌 Pine 相关代码（许可污染实证）。

---

## 9. 总产出（跑完交回）

`poc-vela/REPORT.md`，含四件：

1. **需求满足度矩阵**：
   | 点 | 结论（✅/🟡/❌） | 证据 | 备注 |
   |----|----------------|------|------|
   | P1 | | evidence/p1/ | |
   | … | | | |
2. **硬伤清单**（如有——任何 ❌ 自动触发回退讨论）；
3. **集成方案草图**：适配层接口草案（vela_adapter 的函数清单——我们的 add_drawing/set_markers/set_view_range ↔ Vela API 的映射表）；
4. **遗留疑虑**（🟡 项的 workaround 清单）。

**纪律**：全绿→换底放行（0.5 施工单开写）；任一 ❌→停，报告用户裁决（回退 or 议 workaround）；🟡→记录，不影响放行但入施工单注意事项。

---

*实验单：小一，2026-10-01。执行方=写码会话。结果绑定 Vela 版本号（VERSION.md）。*
