"""贝叶斯优化器：内置 TPE-lite（好/坏组独立分类分布 + 密度比接受）。

零依赖、可复现；不承诺全局最优。实现细节复用 core.optimizer 的纯函数。
"""

OPTIMIZER_API = 1
NAME = "贝叶斯（TPE-lite）"
DESC = "用已试结果猜下一组；适合中等空间、预算有限。"
PARAMS = {}
PARAM_META = {}
CAPS = {"continuous": False, "multi_objective": False,
        "requires_full_space": False, "custom_score": False}

import ast

from agentkline.core import optimizer as opt


def _key(params):
    return tuple(sorted((k, repr(v)) for k, v in params.items()))


def init(ctx):
    return {"tried": [], "observations": []}


def ask(state, ctx):
    tried = {ast.literal_eval(x) for x in (state.get("tried") or [])}
    candidate = opt.propose_tpe(
        ctx["space"]["values"],
        state.get("observations") or [],
        ctx["rng"],
        tried,
    )
    if candidate is None:
        return None
    state.setdefault("tried", []).append(repr(_key(candidate)))
    return candidate


def tell(state, ctx, trial):
    if trial.get("status") == "ok" and trial.get("score") is not None:
        state.setdefault("observations", []).append({
            "params": trial.get("params") or {},
            "score": trial.get("score"),
        })
