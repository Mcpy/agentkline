# core 测试

在仓库根目录跑：

```bash
python -m unittest discover -s engine/core/tests -t engine/core/tests -p "test_*.py"
```

- `cases/*.csv` 由 `make_cases.py` 生成（确定性，别手改）；
- `cases/*.json` 是 run spec，相对路径按 spec 所在目录解析；
- `cases/expected/*.result.json` 由 `make_golden.py` 生成，改口径后重跑并 review diff；
- `test_metrics_parity.py` 需要主包可 import（对照 `agentkline.core.results`）；
- `test_perf.py` 是 5 万根基线，单跑约 0.3s。
