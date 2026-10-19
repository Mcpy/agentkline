# Vela 0.8.4 升级回归存证（P0）

- 日期：2026-10-17（dsh 主机执行）
- 版本：@luxalgo/vela 0.8.1 → **0.8.4**（npm 发布 2026-10-13）
- sha256（min）：4071c32b8cb65e5b75eefb5a6973babc1a90b3f875e44b7d5dad32be181a606f（vendor 与 web_dist/assets 与 regression package 三处一致，sha256sum -c OK）
- 备份：snapshots/pre-vela-0.8.4_20261017-0049.tar.gz（0.8.1 时期 frontend/src+vendor+web_dist+PoC 版本文件）
- 浏览器：mcphub playwright-cdp 远程 Chrome（非本机 chromium；runner.py 的 /usr/bin/chromium 在 dsh 不存在，改用 MCP 浏览器逐页跑）

## 六点回归 + P7 补验（p1–p7 全绿，每页 console error=0）
- p1 values 直喂：registerNativeIndicator ×2、主图叠加、独立副图+underwater 填充、pane inspect、缩放联动 ✅（唯一 console 条目=favicon 404，无害）
- p2 自定义 dataFeed：feed.load 500 根、subscribe=WS 连接点、WS 推 bar #501-#504 → onBars 重算重发全链路 ✅
- p3 画线：add×5 类型、CRUD、all()、toJSON/fromJSON 往返无损 YES、drawing:created/removed fired ✅
- p4 标记：marks.add×6+panel reason+聚簇、MarkerSeries 箭头 emit、marks.all()=7 ✅（groupDefinitions 运行时缺=0.8.1 已知遗留，未恶化）
- p5 bundle 集成：API 覆盖 12/12、ready 26ms、零构建链共存 ✅（页面文案中 960K 为 0.8.1 静态字串；0.8.4 min 实测 1,043,818 B，仍 ≤2MB 软线）
- p6 架构边界：零引擎（registerEngine=0）、license Apache-2.0、AGPL grep 0、deps 仅 @zag-js 七件 ✅
- p7 补验四点：attribution=false 无异常、viewport:changed fired、setMarket→market:changed fired、isGroupVisible 初/关/开 ✅

## e2e
- test_e2e.py：**129 passed, 0 failed**（需 AGENTKLINE_TOKEN 环境变量；agent 端口自本次部署起带 Bearer 鉴权）

## 环境注记
- 远程 CDP 浏览器 webgl2=false（Vela 走降级渲染路径），故像素级视觉验收保留在用户浏览器进行（惯例）；DOM/API 级回归结论不受影响。
- 0.8.2–0.8.4 changelog 无 backfill 直接修复；左滑只加载一次的 bug 预期仍在，留待 P1 重写处理。

## P2/P3 指标通道补验（p8–p9，2026-10-18/19，dsh）
- p8 emit 视觉口：`registerNativeIndicator` + `ctx.emit({series, fills})` 挂 bands（3 线 + 上下轨 fill）与 `kind:'circles'`（sar 圆点）→ RESULT PASS（bands(fill)+circles both mount）。
- p9 每实例组 + priceLines + 隐藏 anchor：
  - `addNativeIndicator(type, {id, title})` 对 `registerNativeIndicator` 注册的类型**不生效**：`ctx.id` 仍为 `native-N`，`panes.list()` 里 title 仍是 descriptor 标题（内置指标才吃 id/title）⇒ 组键只能落 **type 名**；每指标一个 type + 改名走 `unregisterNativeIndicator` + 重注册 + 重挂载（A1/A2 FAIL 为**预期结论**，非缺陷）。
  - `emit({priceLines})` 挂载 OK（`inspect().totals.priceLines=3`）；`display:{pane:false,legend:false,dataWindow:false}` 的隐藏 anchor series + 三条 zone fill 挂载 OK（`totals.fills=3`，series 计 5=1 值线+4 anchor）⇒ RSI 原生 boundedOscillator 形态可在 emit 口 1:1 复刻（B1/B2 PASS）。
- 像素级复核（远程 CDP 降级渲染仍可读数）：RSI pane 直方图出现 `30,32,36`/`20,32,33`/`38,24,28` = 中带/超卖区/超买区三色；MACD pane 出现 `8,153,129`/`14,88,77`/`131,38,47`/`242,54,69` = 原生动能四态 + `120,123,134` 零轴。
