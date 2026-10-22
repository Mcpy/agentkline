---
name: strategy-authoring
description: 如何编写 AgentKline 策略脚本（strategy/*）——signal 内核契约：STRATEGY_MODE/NAME/WARMUP/PARAMS 等字面声明、main(params, ohlcv) 返回目标权重数组、次开盘成交与保护口径、参数/保护校验、save_script 保存即验、run_backtest 跑回测、常见错误码与反模式。写 strategy/* 或跑回测前必读。
---

# AgentKline 策略脚本编写（signal 内核）

## 这是什么

策略脚本**只产出目标权重**（每根 K 线想拿几成仓），撮合、费用、滑点、权益、统计全部由引擎算。
一个 `.py` 文件 = 一个策略，引用 id 为 `strategy/<name>`。

## 存放与 id

- 双根：builtin（包内只读）/ custom（scripts_dir，可写）。**你写的只落 custom**：
  `save_script(id="strategy/xxx", code=...)`（保存即验）或 REST `POST /api/scripts`。
- **id = kind/name**，`name` 限 `[a-z0-9_]+`；裸文件名 = `SCRIPT_BAD_ID`。同名 custom 覆盖 builtin。
- 保存后 `list_strategies` 能看到，`strategy_meta(script="strategy/xxx")` 能读声明。

## 声明块（模块顶层，必须是字面量）

```python
STRATEGY_MODE = "signal"     # 必填，目前只支持 "signal"
NAME = "双均线"               # 必填，显示名
DESC = "快线上穿慢线做多"      # 可选，列表里的说明
WARMUP = 30                  # 必填，>=0：前 N 根不交易、不计绩效
PARAMS = {"fast": 10, "slow": 30}   # 必填，值必须是 JSON 标量（str/int/float/bool/None）
PARAM_META = {               # 可选，给参数表单
    "fast": {"type": "int", "min": 2, "max": 200, "step": 1, "label": "快线"},
}
PROTECTION = {"stop_loss_pct": 0.05, "take_profit_pct": 0.10}  # 可选
BARS_PER_YEAR = None         # 可选：不填=按数据观测密度年化
```

规则：

- 声明必须是**字面量**（`WARMUP = 2 + 3` 会被拒，`STRATEGY_INVALID`）；AST 静态读取，不执行。
- `PARAM_META` 的键必须在 `PARAMS` 里；允许键：`type`(int/float/bool/str)、`min`、`max`、`step`、`label`、`options`、`description`。
- `PROTECTION` 只认 `stop_loss_pct` / `take_profit_pct`，取值 `(0,1)`；未知键报 `PROTECTION_UNKNOWN_KEY`。
- **不要声明 `DIRECTION`**：做多/做空/双边是运行参数，由调用方决定。

## main 契约

```python
def main(params, ohlcv):
    return {"target": [...], "reason": [...]}
```

- 只被**调用一次**，拿到整段 K 线；策略内部自己循环算指标（纯 Python 即可，见"依赖"）。
- `params`：`PARAMS` 默认值 + 本次覆盖合并后的 dict。
- `ohlcv`：bar 字典列表，每根**只有**这 6 个键：
  `{"timestamp": <ms 整数>, "open", "high", "low", "close", "volume"}`。
- `target`：与 `ohlcv` **等长**的数组，元素是有限数；`1`=满仓多、`0`=空仓、`-1`=满仓空、中间连续（0.5、-0.3 合法）。
  超出 `[-1,1]` 会被裁剪并记 warning；含 NaN/Inf 报 `TARGET_NONFINITE`。
- `reason`：可选，等长字符串数组，用于成交归因（`entry_reason`/`exit_reason`）；空串合法。
- 返回裸数组也可以（等价于只给 target），但推荐显式 dict。
- 不要 async、不要 `*args`，main 必须正好两个位置参数。

## 引擎怎么执行（写策略时按这个假定）

1. bar `t` 收盘后，`target[t]` 生效；在 bar `t+1` 的**开盘**成交（收盘确认、次开盘执行）。
2. 权重按**权益**折算数量（1x、连续数量、无杠杆），引擎负责手续费/滑点/现金约束。
3. 同方向小幅漂移会被防抖带忽略（默认 1bp 相对漂移），不会每根 bar 都交易。
4. `direction` 在运行时裁剪：`long_only` 把负目标压成 0、`short_only` 把正目标压成 0；全裁掉时结果 `status=no_signals`。
5. `PROTECTION` 是**开仓均价**级的：多头 stop=均价×(1-sl)、take=均价×(1+tp)；跳空按开盘价、盘中按触发价，同一根先止损后止盈。
6. `WARMUP` 之前的 target 不执行、不计绩效；回测窗口前会自动多灌 WARMUP 根做指标预热。
7. 区间最后一根收盘强制平仓（`exit_reason=end_of_backtest`）。

所以：**不要自己算仓位、现金、费用、权益**，也不要假设能加杠杆。

## 最小模板

> 模板唯一来源：内置策略 `strategy/ma_cross`。加载技能时会把源码原样内联到下面，
> 改模板只改那份脚本（`agentkline/resources/scripts/strategy/ma_cross.py`），别在技能里另抄一份。

<!-- include:strategy/ma_cross -->

注意：warmup 段也要给 `0.0`（长度必须全覆盖），`WARMUP` 建议 ≥ 指标最大回看。

## 保存 → 校验 → 跑

```text
save_script(id="strategy/my_ma", code="<上面全文>")      # 保存即验，返回 ok 或错误码
strategy_meta(script="strategy/my_ma")                  # 读 NAME/WARMUP/PARAMS/PARAM_META/errors
run_backtest(board_id="<板>", script="strategy/my_ma",
             direction="long_only", params={"fast": 8},
             protection={"stop_loss_pct": 0.05},
             start_time=None, end_time=None, limit=20000)
get_result(result_id="<返回值里的 result_id>", section="summary")
```

- `board_id` 用 `list_boards` / `overview` 找现成现场（没有就先 `create_board`）。
- `run_backtest` 跑的是该画板已载入的 K 线；`start_time/end_time`（毫秒）可选，
  缺省=最新往回 `limit` 根，历史不够会自动补。
- 参数越界、未知参数、保护键非法都会在跑之前被拒（错误码透传）。
- 失败时返回 `{"error": "CODE: 说明"}`，按错误码修脚本，不要盲改。

## 常见错误码

| 错误码 | 原因 | 怎么修 |
|---|---|---|
| `STRATEGY_INVALID` | 语法错 / 声明非字面量 / 缺 NAME/WARMUP/PARAMS / main 签名不对 | 按声明块改，表达式换成常量 |
| `MODE_MISMATCH` | `STRATEGY_MODE` 不是 `"signal"` | 写成 `"signal"` |
| `MAIN_MISSING` | 没有可调用的 `main` | 定义 `def main(params, ohlcv)` |
| `PARAMS_INVALID` | 参数类型/范围不对，或 PARAM_META 写错 | 按 PARAM_META 给值；meta 键必须在 PARAMS 里 |
| `PARAM_UNKNOWN` | 覆盖了未声明的参数 | 只传 PARAMS 里的键 |
| `PROTECTION_UNKNOWN_KEY` / `PROTECTION_INVALID` | 保护键不在白名单 / 取值不在 (0,1) | 只用 stop_loss_pct、take_profit_pct |
| `TARGET_LENGTH` | target 长度 ≠ len(ohlcv) | 每根都给值（含 warmup 段） |
| `TARGET_NONFINITE` / `TARGET_INVALID` | NaN/Inf 或非数字 | 计算前处理除零、空窗 |

## 反模式

- **未来函数**：`target[i]` 用 `ohlcv[i+1]` 或窗口外的数据。规矩是"bar i 收盘做决定"，只用 `<= i` 的数据。
- **返回数量/金额**而不是权重：`target=[100]` 不是"买 100 股"，是 100 倍权益（会被裁到 1）。
- **长度对不上**：只算有指标的段、warmup 段漏掉，必报 `TARGET_LENGTH`。
- **依赖 numpy/pandas**：引擎 venv 没有这两个包，`import` 会失败（`ENGINE_INTERNAL`）。用纯 Python。
- **O(n²) 指标**：50k 根要在数秒内跑完，滚动和请用前缀和/滑动窗口，别每根重算整段。
- **把参数写死**：能调的走 `PARAMS`，并在 `PARAM_META` 里给类型/范围，前端才能生成表单。
- **联网/读写文件**：子进程里失败会拖垮整次回测；策略保持纯函数式。
- 不要 print 刷屏：日志会进 stderr，不影响结果但没有意义。

## 自检

- 声明全是字面量？`STRATEGY_MODE="signal"`？`WARMUP` ≥ 指标回看？
- `main` 正好两个参数、不是 async？target 与 ohlcv 等长、全有限、warmup 段有 0？
- 只用了 `<= i` 的数据？权重在 `[-1,1]`？
- 参数都在 `PARAMS` 里、`PARAM_META` 范围正确？
- 纯 Python、无 NaN、O(n)？50k 根能跑完？
- 保存后 `strategy_meta` 的 `errors` 为空？
