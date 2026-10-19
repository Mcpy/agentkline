---
name: indicator-authoring
description: 如何编写 AgentKline 指标脚本——main(params, ohlcv)→values|{values,lines,markers,levels,polylines} 契约、字面元数据族、多线/特殊输出、SUBPLOT 副图声明、recipe/blob 落盘与 inst_id、重算窗口约束。写 indicator/* 脚本前必读。
---

# AgentKline 指标脚本编写

脚本由 `script_engine` 在隔离命名空间 exec（L1 沙箱：不限 import，自律）。
人类版同文见 `docs/脚本编写指南.md`；冲突以本 skill 为准。数据源脚本见姊妹卷 `datasource-authoring`。

## 存放与 id
- 双根：builtin（包内 resources/scripts，只读）/ custom（scripts_dir，可写）。**你写脚本只落 custom**：
  `save_script(id, code)`（保存即校验）或 REST `POST /api/scripts`。
- **id = kind/name**（kind∈datasource|indicator|strategy；name 限 [a-z0-9_]+）。裸文件名 = `SCRIPT_BAD_ID`。
- 契约由目录推断；同名 shadow custom 优先（list_scripts 的 source 字段标明）。

## 字面元数据族（ast 静态抽取，必须字面）
```python
NAME = "显示名"
DESC = "描述（选脚本依据）"
PARAMS = {"k": v}                       # 默认参数（如 {"periods": [5, 10, 20]}）
CAPS = {"backfill": bool, "symbols": bool, "ticker": bool}   # 指标族通常全 False/不声明
```
- **CAPS 声明⇒必须实现**，否则 `CAPS_MISMATCH`。指标族一般不声明任何能力。

## indicator 契约
`main(params, ohlcv) → values | {values, lines, markers, levels, polylines}`；与 K 线等长；warmup=None；禁 NaN/Inf。
`levels`=参数相关水平线 `[{price,title,color?,lineStyle?}]`；`polylines`=`[{key,points:[{x:时间戳ms,price}]}]`；
`markers`=`[{time,position:'aboveBar'|'belowBar',shape}]`（zigzag/fractal 即走这两条）。
lines 项 `{name, values}` 就够——**只出计算值**：类型/颜色/线宽/填充带/圆点/水平线由前端中间层
（`frontend/src/visual_spec.js`，按 script id + 线名）统一决定，内置指标一律不带 type/style。
自定义脚本仍可带 `type: line|histogram|columns|circles|cross|area|step` 与
`style: {color, lineWidth, lineStyle}` 作**兜底**（仅当该 script 未进中间层规格表时生效）。
可选 `label(params)` 定制显示名。
重算只喂最近 max_window=5000 根——长记忆参数勿超窗。
落盘：`add_indicator(script=id, params=...)`=recipe（随 K 线自动重算）；直接给 values/lines=blob
（钉死单周期，传 scope 报错）。实例名 inst_id：撞名 INST_EXISTS；不传自动 `macd_2` 式。

## 多线与特殊输出
- 一个实例可返回多条 `lines`（BOLL 三轨）；内置 SMA/EMA 是 Vela 单线语义，多线靠**多实例**。
- 特殊输出：zigzag 用 `polylines`，fractal 用 `markers`；其余一律 `lines`。

## SUBPLOT 声明
- 字面常量 `SUBPLOT = True`：副图族指标声明；add_indicator 未显式传 subplot 时
  按此自动归属并建/删副图（命名=script stem）；不声明=主图叠加族。
  内置 75 项由 `agentkline/resources/indicator_spec.json` 派生，`overlay=false` 即 `SUBPLOT=True`。

## 自检
id 格式？元数据全字面？与 K 线等长？warmup=None？无 NaN/Inf？lines 项字段齐？SUBPLOT 声明与族一致？
