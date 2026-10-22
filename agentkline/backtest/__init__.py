"""引擎进程边界（v0.6.1 M3）。

后端只通过 `ak-engine` 子进程调用引擎；不 import 任何引擎运行时
（唯一例外：save_script 时的纯 AST 校验，见 core/script_engine.py）。
"""
