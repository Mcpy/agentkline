# Vela PoC 报告（决策门）

**版本绑定**：@luxalgo/vela **0.8.1**（npm，2026-10-03；sha256 见 VERSION_HASH.txt；bundle min=960K / full=1.9M）。
**执行**：poc-vela/ 独立目录，headless chromium（poc_runner.py）逐页跑 p1–p6，console+DOM+截图存证 evidence/。
**纪律核对**：主项目零改动 ✅；未安装 pinets/vela-pinets ✅；实验页全程零 registerEngine ✅。

---

## 1. 需求满足度矩阵

| 点 | 结论 | 证据 | 备注 |
|----|------|------|------|
| **P1 数据线/副图渲染（死穴）** | ✅ | evidence/p1.{png,log} | **路径 A 一次通**：`registerNativeIndicator` + `ctx.emit({series,fills})` = 官方 values 直喂通道；`paneHint:'price'` 主图叠加（双均线跟蜡烛轴）、`paneHint:'new'` 自动开独立副图（equity+归一对照双线同副图）；`fills[]` 画 underwater 半透明填充；`setVisibleRange` 缩放后线跟随=同轴联动目验+数据层同轴 |
| **P2 数据流注入** | ✅ | evidence/p2.{png,log} | 自定义 `MarketDataFeed`（deps.dataFeed 注入，零 provider 注册）：`load` 历史 500 根 / `subscribe(cfg,onBar)` = WS 连接点 / tick→onBar→框架→native `onBars`→重算重发 15/15 全链路 / 新 bar 追加 501–503 实证 |
| **P3 画线程序化+持久化** | ✅ | evidence/p3.{png,log}、evidence/p3/drawings-doc-sample.json | `chart.drawings.add` 五类（hline/trendline/box/text/arrow，anchor 契约 `{time,price}`）+ update/lock/bringToFront/remove；**toJSON→清空→fromJSON 往返无损 YES**；事件 drawing:created/removed fired；74 种 DrawingTypeKey 目录 |
| **P4 交易标记选型** | ✅ 定案=方案甲 | evidence/p4.{png,log}、p4_click.png | 甲 `marks.add` + panel content（reason 字段可读）+ 同 bar 聚簇（7 marks→6 glyph，弹窗列全簇）+ `mark:click` 事件带簇 ids 实测 fired；**推荐甲**（reason 面板+聚簇+group 可见性开关全有） |
| **P5 bundle 集成** | ✅ | evidence/p5.{png,log} | 原生 JS+script 标签零构建链，与假身份证卡/假雷达同页共存；API 覆盖 **12/12**；ready 77ms；min 960K ≤2MB 软线 |
| **P6 架构边界** | ✅ | evidence/p6/license-dep-audit.md、p6.{png,log} | 零引擎断言：registerEngine 调用=0 全功能；许可 Apache-2.0，bundle grep AGPL=0，pinets 仅报错文案串；deps 仅 @zag-js/*；workspace 建议成文（§4） |

**总判：六点全绿，无 ❌ 硬伤。换底放行条件满足。**

## 2. 硬伤清单
**无。**（P1 死穴由官方 native-indicator 通道正面解决，非 workaround。）

## 3. 集成方案草图（vela_adapter 映射表）

| 我们 0.4 语义 | Vela 0.8.1 API | 备注 |
|---|---|---|
| 指标 values 主图叠加/副图 | `registerNativeIndicator({paneHint:'price'/'new'})` + `ctx.emit({series:[LineLikeSeries]})` | 每 board×indicator 一个 native type；values 更新=重 emit（patch 语义） |
| WS 历史/实时/切板 | `deps.dataFeed`：`load`/`subscribe(onBar)`/`setMarket` | feed 内桥接我们 WS；切板=新 chart 或 setMarket（0.5 定） |
| `add_drawing`/`delete_drawing` MCP | `chart.drawings.add(type,{anchors:[{time,price}]})` / `.remove(id)` | anchor 契约已验；type 白名单=trendline/hline/ray/box/text 起步 |
| 画线持久化（白名单文档） | `drawings.toJSON()`/`fromJSON(doc)` | 往返无损已验；doc={version:1,drawings[]} 直接落我们服务端 |
| `set_markers`（交易点+reason） | `chart.marks.add({time,glyph,content:{panel:{items:[{type:'field',label:'reason',...}]}}})` | group='trades' + defineGroup；聚簇自动 |
| AI 划线族标记（箭头） | 同 marks（glyph letter/shape） | MarkerSeries 箭头不绘（遗留②），marks lane 足够 |
| `set_view_range` | `chart.setVisibleRange({from,to})` / `setVisibleRangePreset` | ms epoch |
| equity 子图/持仓带/underwater（0.6） | native indicator `paneHint:'new'` + `fills[]`（eq↔peak）+ backgrounds（持仓带候选） | P1 已验 fills；backgrounds 未单验（同族输出字段，低风险） |
| 指标设置面板 | native descriptor `inputsSchema/defaultInputs/setInputs` | 0.5+ 用 |
| 事件桥（画线/标记/视口） | `chart.on('drawing:created'/'mark:click'/...)` | drawing:updated/selected 未 fired（遗留①） |

**适配层形态**：单文件 `frontend/src/vela_adapter.js`（原生 JS 模块，script 标签引 vela.global.min.js），对上暴露我们现有 render.js 的同名语义函数，render.js 退化为薄壳→0.5 换底时 UI 层零改。

## 4. 遗留疑虑（🟡 不阻放行，入施工单注意事项）

1. **drawing:updated / drawing:selected 事件未 fired**（created/removed 有）——画线编辑回传若依赖事件需轮询 `drawings.all()` diff 兜底；施工单验证项；
2. **MarkerSeries（方案乙）买卖箭头不绘**（emit 无报错、模型层在）——不影响定案（甲更优），若 0.6 需 bar 上箭头再探 shape token 映射；
3. **text/arrow 画线视觉不绘**（模型层+序列化正常）——同上，主力量线族（trendline/hline/box/ray）已目验；
4. **chart.marks.groupDefinitions 运行时缺**（类型层有）——group 可见性开关 UI 若需要，用 `setGroupVisible/isGroupVisible` 替代（未单验，施工单项）；
5. **toJSON 返回活引用**（doc 会被后续 fromJSON 原地改）——适配层必须深拷贝存档（p3 已踩并修正）；
6. **workspace 不在 global bundle**（独立 ESM）——建议=headless core+自建外壳（理由：无构建链/多板语义是服务端名册+单图切换/自有 DOM 外壳/持久化走服务端文档）；若将来真要同屏多 cell grid=引入构建链，另议；
7. **API 未稳**（官方明说）——版本锁 0.8.1；升级=重跑本 PoC 六点回归（runner 已自动化，成本≈10 分钟）。

---

*报告：小一，2026-10-03。结论绑定 Vela 0.8.1。*

## 附：P7 补验（2026-10-03，施工单未验四点）
| 点 | 结论 | 证据 |
|---|---|---|
| ① attribution 开关 | ✅ `chart.renderer.set('attribution',false)` 无异常 + **水印目验消失**（p7.png 左下无 V logo，对照 p1/p3） | evidence/p7.{png,log} |
| ② viewport:changed | ✅ fired=1（setVisibleRange 触发） | 同上 |
| ③ market:changed | ✅ setMarket resolve + fired=1（**dataFeed 模式**；offline data 模式 setMarket 会 park 挂起——集成按 R3 走 dataFeed 无此问题） | 同上 |
| ④ group 可见性开关 | ✅ isGroupVisible 初/关/开 = true/false/true | 同上 |
