# vela-regression —— Vela 升级回归钩子（v0.5 R6-1）
升级 @luxalgo/vela 时：替换 package/ 为新版本 dist → 起 http.server → 逐页跑 runner.py：
    cd tools/vela-regression && python -m http.server 8799 &
    python runner.py p1 p2 p3 p4 p5 p6 p7 p8 p9 p10
全绿=用新版本；红=修 frontend/src/vela_adapter.js（唯一适配点）；修不绿=回退版本。
兼容基线契约 = docs/v0.5-需求与改动点.md §2 映射表（锁契约不锁版本号）。
浏览器：runner 自动找系统 Chrome / playwright 缓存（可用 `AK_CHROMIUM` 指定；缓存浏览器缺系统库时用 `AK_CHROMIUM_LIBS` 指解包目录）。

升级门（v0.5.4 起）：
- 内部面台账：`docs/vela-internals.md`（chrome/scene/coords 等非公开接口，升级前必读）。
- UI 冒烟：`python tools/ui_smoke.py`（6 条浏览器检查，含最新价越界贴边）。
- API e2e：`python test_e2e.py --port <temp-agent-port>`。
