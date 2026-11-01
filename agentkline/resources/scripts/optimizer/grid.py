"""网格优化器：枚举 space 的全部离散组合。

OPTIMIZER_API=1 的脚本契约见 docs/dev/优化器插件开发指南.md。
requires_full_space=True：组合数超过预算时由内核直接拒绝，避免跑到一半才发现放不下。
"""
import itertools

OPTIMIZER_API = 1
NAME = "网格搜索"
DESC = "枚举参数空间的全部组合；适合参数少、想一次看全貌。"
PARAMS = {}
PARAM_META = {}
CAPS = {"continuous": False, "multi_objective": False,
        "requires_full_space": True, "custom_score": False}


def init(ctx):
    values = ctx["space"]["values"]
    keys = list(values)
    combos = [dict(zip(keys, vals))
              for vals in itertools.product(*[values[k] for k in keys])]
    return {"i": 0, "combos": combos}


def ask(state, ctx):
    i = int(state.get("i") or 0)
    combos = state.get("combos") or []
    if i >= len(combos):
        return None
    state["i"] = i + 1
    return combos[i]
