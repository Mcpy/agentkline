# vela-regression —— Vela 升级回归钩子（v0.5 R6-1）
升级 @luxalgo/vela 时：替换 package/ 为新版本 dist → 起 http.server → 逐页跑 runner.py：
    cd tools/vela-regression && python -m http.server 8799 &
    python runner.py p1 p2 p3 p4 p5 p6 p7
全绿=用新版本；红=修 frontend/src/vela_adapter.js（唯一适配点）；修不绿=回退版本。
兼容基线契约 = docs/v0.5-需求与改动点.md §2 映射表（锁契约不锁版本号）。
