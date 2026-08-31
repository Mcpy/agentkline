---
name: script-authoring
description: 如何编写能在 AgentKline 合法运行的指标脚本与数据源脚本——main 签名、返回结构、元数据、warmup/NaN 约束、until 回溯与沙箱边界。写新脚本前必读。
---

# AgentKline 脚本编写指南（skill）

AgentKline 的两类脚本都由 `script_engine` 在隔离命名空间中 `exec` 执行，
通过**约定函数 `main`** 与外部交互。写错签名只会撞 `SCRIPT_NO_MAIN` 这类错，
请先读完本 skill 再动手。参考示例：`scripts/sma.py`（指标）、`scripts/mock_btc_data.py` /
`scripts/ccxt_binance_btc.py`（数据源）。

## 一、指标脚本（indicator）

### 签名
必须定义 `main(params, ohlcv)`（也兼容 `main(params)`，引擎按参数个数自适应）。
执行时全局注入：
- `params: dict` —— 调用方传入的参数；
- `ohlcv: list[dict]` —— K 线，每条 `{timestamp, open, high, low, close, volume}`，
  `timestamp` 为**毫秒**。

### 返回值
- 返回 `list` → 视为单线 `values`；
- 或返回 `dict`：`{"values": [...], "lines": [...], "markers": [...]}`（后两者可选）。
- `values` 必须与 `ohlcv` **等长、逐 bar 对齐**。

### warmup 与 NaN（重要）
- 预热期（如 SMA 前 period-1 根）**用 `None` 占位**，不要返回 `float('nan')`。
- 虽然 v0.3.1 起服务端会把 NaN/Inf 清洗为 `None`（防非法 JSON），但你应主动用 `None`，
  因为 NaN 参与运算会污染后续结果。

### 可选元数据（用于自动命名/设置弹窗）
- `NAME = "SMA"` —— 根名；
- `PARAMS = {"period": 20}` —— 参数默认值；
- `def label(params): return f"SMA({params.get('period',20)})"` —— 自定义显示名。

### 模板
```python
PARAMS = {"period": 20}

def main(params: dict, ohlcv: list) -> list:
    period = params.get("period", 20)
    closes = [b["close"] for b in ohlcv]
    out = [None] * len(closes)          # warmup 用 None
    for i in range(period - 1, len(closes)):
        out[i] = round(sum(closes[i-period+1:i+1]) / period, 2)
    return out
```

### 注册方式
- `add_indicator(board, tf, name, script="xxx.py", params={...})`（推荐，统一入口）；
- 或 `run_script(board, tf, path, save_as="indicator")`（兼容路径）。

## 二、数据源脚本（datasource）

### 签名
定义 `main(params)`，返回 `list`（或 `{"data": [...]}`），元素为 K 线 bar：
`{timestamp(毫秒), open, high, low, close, volume}`，**按时间升序**。

### until 回溯（决定能否 load_history）
- 若支持 `params["until"]`（毫秒），只返回该时间之前的 K 线，则 `load_history`
  可向左补更早历史（前端左滑自动触发）。
- `ccxt_binance_btc.py` 支持；`mock_btc_data.py` 不支持（回溯时 prepended=0）。

### 注册方式
`set_datasource(board, tf, path="xxx.py", params={...}, poll_interval=0)`；
`poll_interval>0` 则轮询实时刷新。

## 三、沙箱边界（自律，别指望兜底）
- 当前为 **L1：直接 exec** 于隔离命名空间，**不限制 import**（内部调试用）。
- 路线图 L2 才上 subprocess 隔离。因此脚本必须自律：无死循环、无恶意 IO、
  控制运行时长（轮询数据源尤其注意）。

## 四、自检清单
- [ ] 定义了 `main`，签名正确；
- [ ] 指标 values 与 K 线等长，warmup 用 `None`、无 NaN；
- [ ] 数据源 bar 含全字段、毫秒、升序；
- [ ] 需要回溯则实现 `until`；
- [ ] 无死循环/长阻塞。
