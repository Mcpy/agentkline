# agentkline-engine-core

AgentKline 回测引擎框架（独立 distribution，不依赖后端）。

包含：

- `contract.py`：`RunRequest` / `RunResult` / `Engine` 协议、`engine_api=1`；
- `bars.py`：K 线读取（CSV / JSON / inline）、时间戳归一、排序去重；
- `loader.py`：策略源码 AST 校验 + 编译加载；
- `matching.py`：撮合核（签名仓位、均价、费用、滑点、保护、强平、`rebalance_tolerance` 防抖）；
- `drivers/signal.py`：signal 策略驱动（target 校验、方向过滤、次开盘成交）；
- `result.py` + `metrics.py`：`schema=1` 结果与 0.6.0 统计口径；
- `registry.py`：entry point 发现（group `agentkline.engines`）；
- `cli.py`：`ak-engine list / run / validate-strategy`。

设计约束：

- 只依赖 Python 标准库；**不得** import `agentkline` / `fastapi` / `uvicorn` / `vela`；
- 后端只通过 `ak-engine` 子进程调用引擎，core 是唯一边界。

## 用法

```bash
pip install -e engine/core          # 或 uv pip install -e engine/core
ak-engine list --json
ak-engine run --spec run.json --out result.json
ak-engine run --stdin               # spec+bars 从 stdin 读，结果走 stdout
ak-engine validate-strategy strategy.py --json
```

`run --stdin` 的输入：

```json
{
  "api": 1,
  "engine": "builtin",
  "bars": [{"timestamp": 0, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0}],
  "strategy": {"source": "NAME='x'\n..."},
  "run": {"initial_cash": 10000, "direction": "long_only"}
}
```

输出：stdout 第一行哨兵 `__AK_RESULT__`，第二行起是单行结果 JSON；日志与用户 `print` 全部走 stderr。

退出码：`0` 成功、`2` 输入/契约错误、`3` 崩溃、`4` 超时、`5` 引擎内部错误。
错误同样以 `__AK_RESULT__` + `{"error": {"code": ..., "message": ...}}` 输出，便于后端统一解析。

## 引擎插件

第三方引擎实现 `Engine` 协议并注册 entry point：

```toml
[project.entry-points."agentkline.engines"]
myengine = "my_pkg.engine:MyEngine"
```

内置引擎在**主包** `agentkline.engines.builtin`，不单独发布。
