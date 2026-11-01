---
name: optimizer-authoring
description: 如何编写 AgentKline 优化器脚本（optimizer/*）——OPTIMIZER_API=1 契约、init/ask/tell/rank/summarize 钩子、PARAMS/PARAM_META 优化器参数、CAPS（连续空间/多目标/全空间）、候选与非法值处理、保存校验、跑寻优与读报告。写 optimizer/* 或扩展参数搜索算法前必读。
---

# AgentKline 优化器脚本编写

## 这是什么

优化器脚本只决定“下一步试哪组参数、最后怎么排序”，**不跑回测、不算账、不登记结果**。
回测执行、预算、样本内外切分、Top K 登记都由内核负责。

一个 `.py` = 一个优化器，id 为 `optimizer/<name>`。内置 `grid / random / bayes` 只是示例；
GA、PSO、加权目标、Pareto 等都应作为自定义优化器接入，不必改内核。

## 存放与 id

- 双根：builtin（包内只读，`resources/scripts/optimizer/`）/ custom（`scripts/optimizer/`，可写）。
- **你写的只落 custom**：`save_script(id="optimizer/xxx", code=...)`（保存即验）或 REST `POST /api/scripts`。
- id = `optimizer/name`，name 限 `[a-z0-9_]+`；裸文件名 = `SCRIPT_BAD_ID`；同名 custom 覆盖 builtin。
- 保存后 `list_optimizers` 能看到，返回 `id/name/desc/source/params/param_meta/caps/api`。

## 声明块（模块顶层，必须是字面量）

```python
OPTIMIZER_API = 1            # 必填，目前只支持 1
NAME = "遗传算法"             # 必填，显示名
DESC = "种群 + 交叉 + 变异"   # 可选，列表说明

PARAMS = {"population": 20, "mutation": 0.1}   # 优化器自己的参数
PARAM_META = {                                    # 给 UI 的表单 schema
    "population": {"type": "int", "min": 5, "max": 200, "label": "种群"},
    "mutation": {"type": "float", "min": 0, "max": 1, "label": "变异率"},
}

CAPS = {"continuous": False, "multi_objective": False,
        "requires_full_space": False, "custom_score": False}
```

规则：

- `OPTIMIZER_API`、`PARAMS`、`PARAM_META`、`CAPS` 必须是字面量；AST 静态读取，不执行。
- 必须有 `def ask(state, ctx)`；没有 `OPTIMIZER_API` 报 `SAVE_OPTIMIZER_API`，没有 `ask` 报
  `SAVE_OPTIMIZER_ASK`，元数据非法报 `SAVE_OPTIMIZER_META`。
- `PARAMS`/`PARAM_META` 与策略参数同构；`PARAM_META` 的键应在 `PARAMS` 里。
- 优化器参数由请求 `optimizer_params` 覆盖，内核按 `PARAM_META` 校验后放进 `ctx["params"]`。

## 钩子契约

```python
def init(ctx):
    """每个作业调用一次；返回本作业的 state（建议 JSON 可序列化）。"""
    return {}

def ask(state, ctx):
    """返回下一组策略参数 dict；None = 搜索结束。必填。"""
    ...

def tell(state, ctx, trial):
    """每组试次跑完后回调；trial 含 params/status/score/value/is_stats。"""

def rank(state, ctx, trials, phase):
    """自定义 Top K 排序；phase='is'|'oos'；返回 trial 下标列表，None=回落标量分。"""
    return None

def summarize(state, ctx):
    """报告附加字段（如 Pareto front、种群收敛）；返回 dict。"""
    return {}
```

- `state` 是每个作业独立的一份 dict；跨 `ask`/`tell` 的状态放这里，**不要用模块级可变变量**。
- `ctx` 每次调用重建，包含：
  - `space`：`{raw, values, base, meta, size}`；`values` 是展开后的离散候选，
    `base` 是策略默认值，`meta` 是 `PARAM_META`；
  - `objective`、`constraints`；
  - `budget`：`{max_runs, max_seconds}`；
  - `seed`、`params`、`history`（已跑试次副本）、`done`、`elapsed_ms`；
  - `rng`：按 seed 初始化的 `random.Random`，可直接用。
- `trial` 关键字段：`index/params/status/score/value/reason/is_stats`；
  样本外补 `oos_status/oos_score/oos_value/oos_stats/overfit_*`。

## 内核与脚本的边界

| 内核负责 | 脚本负责 |
|---|---|
| 参数空间校验、候选值校验 | 提议候选（`ask`） |
| 跑回测、单组异常隔离 | 消费试次（`tell`） |
| 预算、超时、取消 | 可选排序（`rank`） |
| 样本内/外切分、Top K 登记 | 可选报告附加（`summarize`） |
| 标准单目标评分/约束/过拟合提示 | 多目标/自定义排序 |

不要把 `min_trades`、`max_drawdown`、IS/OOS 口径在脚本里重写一遍；标准场景直接用内核评分，
只有多目标或特殊算法才用 `rank` 覆盖排序。

## CAPS 怎么选

| cap | 含义 |
|---|---|
| `continuous` | 候选可不在 `space.values` 里（只要在 `PARAM_META` 范围内）；总数按预算 |
| `multi_objective` | `objective` 允许自由结构；内核不强行解析单指标，试次 `score=None` |
| `requires_full_space` | 空间组合数超过预算直接拒绝（grid 用） |
| `custom_score` | 预留能力位；当前自定义排序用 `rank` 即可 |

连续空间 / GA / PSO：`CAPS.continuous=True`，`ask` 返回任意合法值；内核会按
`PARAM_META` 的类型/min/max 校验，不要求在 `values` 列表里。

## 多目标 / Pareto

`CAPS.multi_objective=True` 时：

- 请求的 `objective` 原样进 `ctx["objective"]`，可以是 `{"metrics": ["sharpe", "total_return"]}`
  或权重结构；
- 内核只做约束判定，不生成单指标 `score`；
- `rank(state, ctx, trials, phase)` 用 `trial["is_stats"]` / `trial["oos_stats"]` 自己排序；
- 返回的下标顺序就是 Top K 顺序；报告 `ranked_by="optimizer"`；
- `summarize` 可把 Pareto front 放进 `report.extra`。

多目标不作为内置优化器发布；这是扩展接口。最小示例：

```python
CAPS = {"continuous": False, "multi_objective": True,
        "requires_full_space": False, "custom_score": False}
PARAMS = {"w_sharpe": 0.6, "w_return": 0.4}
PARAM_META = {"w_sharpe": {"type": "float", "min": 0, "max": 1},
              "w_return": {"type": "float", "min": 0, "max": 1}}

def rank(state, ctx, trials, phase):
    ws = float(ctx["params"].get("w_sharpe") or 0)
    wr = float(ctx["params"].get("w_return") or 0)
    def val(t):
        s = (t.get("oos_stats") if phase == "oos" else t.get("is_stats")) or {}
        return ws * float(s.get("sharpe") or 0) + wr * float(s.get("total_return") or 0)
    return [i for i, _ in sorted(enumerate(trials), key=lambda x: -val(x[1]))]
```

## 最小模板

> 模板唯一来源：内置优化器 `optimizer/random`。加载技能时会把源码原样内联到下面；
> 改模板只改那份脚本，别在技能里另抄一份。

<!-- include:optimizer/random -->

注意：`state["tried"]` 用可序列化的字符串 key；不要在 state 里放 set / 自定义对象。

## 保存 → 校验 → 跑

```text
save_script(id="optimizer/my_ga", code="<上面全文>")     # 保存即验
list_optimizers()                                       # 看内置/自定义与 PARAMS
run_optimization(
  board_id="<板>", timeframe="1d", script="strategy/my_ma",
  space={"fast": {"min": 5, "max": 30, "step": 1},
         "slow": {"values": [20, 30, 60]}},
  method="optimizer/my_ga",
  optimizer_params={"population": 30, "mutation": 0.15},
  objective={"metric": "sharpe", "direction": "max"},
  constraints={"min_trades": 10, "max_drawdown": 0.4},
  budget={"max_runs": 40, "max_seconds": 600},
  holdout={"ratio": 0.3, "top_k": 3}, seed=42)
optimization_status(job_id="<返回值>")                   # 轮询到 status != running
```

- `method` 用 `optimizer/xxx`；旧 `grid/random/bayes` 自动映射到同名内置。
- `run_optimization` 立即返回 `{job_id, total, optimizer, optimizer_params, ...}`；
  报告里看 `optimizer`、`optimizer_params`、`ranked_by`、`top/best`、`warnings`。
- 只登记 Top K（有 holdout 时是样本外 Top K）；完整试次在报告里。

## 常见错误与反模式

| 现象 | 原因 / 修法 |
|---|---|
| `SAVE_OPTIMIZER_API` | 没写 `OPTIMIZER_API = 1` |
| `SAVE_OPTIMIZER_ASK` | 没定义 `ask(state, ctx)` |
| `SAVE_OPTIMIZER_META` | `PARAMS/PARAM_META/CAPS` 不是字面量或类型不对 |
| `OPTIMIZER_PARAM_INVALID` | `optimizer_params` 未知键或超出 `PARAM_META` 范围 |
| `OPTIMIZE_CANDIDATE_INVALID` | `ask` 返回了未知参数/越界值；该行记 `invalid`，仍扣预算 |
| `OPTIMIZE_RANK_FAILED` | `rank` 抛错或返回非法下标；内核回落标量排序并给 warning |
| 作业卡在 running | `ask` 内长时间阻塞；超时只在两组之间检查 |
| 每次结果不可复现 | 用了全局 `random`；改用 `ctx["rng"]` 或 `random.Random(ctx["seed"])` |
| 自定义参数改了但不生效 | 没放进 `PARAMS`，或请求没传 `optimizer_params` |

## 检查清单

- [ ] `OPTIMIZER_API = 1`、`NAME`、`ask` 都有？
- [ ] `PARAMS/PARAM_META/CAPS` 是字面量？
- [ ] 状态放在 `state`，没有模块级可变变量？
- [ ] 候选在 `PARAM_META` 范围内？连续空间声明 `CAPS.continuous`？
- [ ] 预算内能返回 `None` 收尾？
- [ ] 多目标用 `CAPS.multi_objective + rank`，并处理 `phase='is'|'oos'`？
- [ ] 没有在脚本里重复实现回测/约束/登记？
