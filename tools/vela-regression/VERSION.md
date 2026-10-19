# vela-regression 版本绑定
- 当前基线：@luxalgo/vela **0.8.4**（2026-10-17 升级；npm 发布 2026-10-13）
- sha256（dist/vela.global.min.js）：4071c32b8cb65e5b75eefb5a6973babc1a90b3f875e44b7d5dad32be181a606f
- sha256（dist/vela.global.js）：af13eed0ce6660f7dca4e6c7c4468933104873d2600844eb5c7854cb3434918b
- 前任基线：0.8.1（sha 40f39542d99863bda652c225c84e2d28c28d25c1604447111e77b76bfc135e45，见 poc-vela/VERSION.md，历史 PoC 绑定保留不动）
- 纪律：锁契约不锁版本号；升级=重跑 **p1–p9** 九点回归（p8=emit 视觉口 bands/circles，p9=每实例 emit 组 + priceLines + 隐藏 anchor）；绿=用新版，红=修 vela_adapter.js，修不绿=回退
