---
name: script-authoring
description: 如何编写能在 AgentKline v0.4 合法运行的指标/数据源脚本——id=kind/name、main 签名、字面元数据族(NAME/DESC/PARAMS/CAPS/IDENTITY)、CAPS 一致性、until 回溯可重放、数据家族范式、板锁语义与沙箱边界。写新脚本前必读。
---

# AgentKline 脚本编写（v0.4 skill）

脚本由 `script_engine` 在隔离命名空间 exec（L1 沙箱：不限 import，自律）。
人类版同文见 `docs/脚本编写指南.md`；冲突以本 skill 为准。

## 存放与 id
- 双根：builtin（包内 resources/scripts，只读）/ custom（scripts_dir，可写）。**你写脚本只落 custom**：
  `save_script(id, code)`（保存即校验）或 REST `POST /api/scripts`。
- **id = kind/name**（kind∈datasource|indicator|strategy；name 限 [a-z0-9_]+）。裸文件名 = `SCRIPT_BAD_ID`。
- 契约由目录推断；同名 shadow custom 优先（list_scripts 的 source 字段标明）。

## 字面元数据族（ast 静态抽取，必须字面）
```python
NAME = "显示名"
DESC = "描述（选脚本依据）"
PARAMS = {"k": v}                       # 默认参数
CAPS = {"backfill": bool, "symbols": bool, "ticker": bool}
IDENTITY = ["symbol"]                  # 板锁身份键；路径可换源用 []
```
- **CAPS 声明⇒必须实现**，否则 `CAPS_MISMATCH`：backfill⇒main 签名含 `until`；symbols⇒def list_symbols(query)；ticker⇒def ticker(params)。不声明=无能力。
- CAPS 门控产品功能：backfill=左滚补历史；symbols=标的搜索索引；ticker=自选表报价(0.4.1)。

## indicator 契约
`main(params, ohlcv) → values | {values, lines, markers}`；与 K 线等长；warmup=None；禁 NaN/Inf。
lines 项 `{name, type: line|histogram, values, style?}`。可选 `label(params)` 定制显示名。
重算只喂最近 max_window=5000 根——长记忆参数勿超窗。
落盘：`add_indicator(script=id, params=...)`=recipe（自动重算）；给 values/lines=blob（钉死单周期，传 scope 报错）。
实例把手 inst_id：撞名 INST_EXISTS；不传自动 `macd_2` 式。

## datasource 契约
`main(params, until=None) → [{timestamp(ms), o,h,l,c,v}, ...]`；timestamp 毫秒。
- poll/once 是槽配置（poll_s），非脚本属性。
- until 回溯：返回早于 until 的 bars；有界就在边界返回空。**跨窗连续+可重放**（同(身份,日期)同值；
  范式=创世点+逐日确定性种子，见内置 datasource/mock_btc）。
- list_symbols(query) → [{symbol, display}]；索引首用全量+TTL 日级，搜索不穿透交易所。
- ticker(params) → {last, change, change_pct}。
- 单槽上限 max_bars_per_slot=50000（截旧+dropped）；**别内嵌巨量数据**，优先自拉；save >100KB 告警。

## 数据家族范式
多数据集/多周期 = 单脚本 + 非身份 params 键分片（dataset/interval）。**禁止拆多脚本**（板锁全等校验会拒）。

## 板锁语义（上下文）
画板=现场：source_lock={script, identity快照}；建板即锁/空板首配即锁；换标的/换源=新建画板
（撞锁 SOURCE_LOCKED+suggestion）；IDENTITY 外 params 自由改（改即重拉）。
在线板加周期系统注入 {identity+interval}——脚本读 params["interval"] 支持多周期。

## 自检
id 格式？元数据全字面？CAPS 与实现一致？指标等长/warmup/无 NaN？数据源毫秒/until 语义/可重放？
未内嵌超量？多面板单脚本？

## 周期语义（v0.4 优化点 2）
- 字面常量 `INTERVALS = [...]`（ast 族）：声明=实时源；不声明=离线源（自由槽面板语义）。
- 系统：建板即锁默认 `[15m,1h,4h,1d,1w] ∩ INTERVALS`（初始当前=1d 在列则用），全部初始槽自动注入配置；
  空板首配锁不扩槽（尊重 AI）。每槽配置恒注入 `interval=槽名`——脚本读 `params["interval"]` 出粒度，
  IDENTITY 不含 interval。"+"按钮下拉=INTERVALS−已有；加入按短→长排序；不支持→INTERVAL_UNSUPPORTED；
  切到未配置槽=懒配置自愈。
- 作者义务：INTERVALS 每档真能出对应粒度；单粒度源声明单档。


## 报价契约 CAPS.ticker（v0.4.1）
- `CAPS.ticker=True` ⇒ 实现 `ticker(params)→{price(必需数值), ts, change_pct?, extra?}`（键白名单）；
  保存即校验 CAPS_MISMATCH；运行时形状违 TICKER_BAD_SHAPE；雷达只盯有徽章源（无=TICKER_UNSUPPORTED）。
- 实时源建议同给 ticker（visible 板心跳价）；离线源声明 False。参考 builtin ccxt_binance/mock_btc。


## 批量报价 tickers()（v0.4.1 性能②，可选）
- `tickers(params_list)->[quote]` 同序返回；雷达按源单请求批量；不实现回退逐行；形状违 TICKERS_BAD_SHAPE。
