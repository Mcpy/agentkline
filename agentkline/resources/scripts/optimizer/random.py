"""随机优化器：在离散候选值里均匀采样，按元组去重。"""

OPTIMIZER_API = 1
NAME = "随机采样"
DESC = "在参数候选值里均匀随机取样；适合大空间、预算有限。"
PARAMS = {}
PARAM_META = {}
CAPS = {"continuous": False, "multi_objective": False,
        "requires_full_space": False, "custom_score": False}


def _key(params):
    return tuple(sorted((k, repr(v)) for k, v in params.items()))


def init(ctx):
    return {"tried": []}


def ask(state, ctx):
    values = ctx["space"]["values"]
    rng = ctx["rng"]
    tried = set(state.get("tried") or [])
    for _ in range(300):
        candidate = {k: rng.choice(vals) for k, vals in values.items()}
        key = _key(candidate)
        key_s = repr(key)
        if key_s in tried:
            continue
        state.setdefault("tried", []).append(key_s)
        return candidate
    return None
