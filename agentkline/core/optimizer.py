"""v0.6.5 参数寻优内核（纯函数，不依赖 numpy/optuna）。

设计要点（定稿见 docs/0.6.5-参数寻优方案.md）：
- 空间 = 每个参数一组离散候选值（range 或 values），统一收敛到参数类型；
- 三种搜索器：grid（全组合，受预算约束）/ random（均匀采样）/ bayes（内置 TPE-lite）；
- TPE-lite 用“好/坏两组参数值的独立分类分布 + 联合接受概率”近似贝叶斯，
  无科学计算依赖、可复现；装了 optuna 也不自动切换，避免行为漂移；
- 目标 + 约束在这里统一评分：ok / rejected（约束）/ invalid（指标不可用）；
- 本模块只算“下一个候选/评分/排序”，跑引擎与登记结果留在 service。
"""
from __future__ import annotations

import itertools
import math
import random
from collections import Counter

# 目标指标白名单：值越大越好（max_drawdown 是负数，越接近 0 越好）
METRIC_DIRECTIONS = {
    "total_return": "max",
    "annual_return": "max",
    "sharpe": "max",
    "sortino": "max",
    "calmar": "max",
    "max_drawdown": "max",
    "profit_factor": "max",
    "win_rate": "max",
}

DEFAULT_OBJECTIVE = {"metric": "sharpe", "direction": "max"}
DEFAULT_BUDGET = {"max_runs": 40, "max_seconds": 600}
DEFAULT_HOLDOUT = {"ratio": 0.3, "top_k": 3}
MAX_SPACE_VALUES = 500          # 单参数候选值上限，防手滑输入 1..100000
MIN_EVAL_BARS = 20              # 样本内/外各自至少可评估的根数


# ---------------------------------------------------------------- 参数空间
def cast_value(key, value, default, meta, prefix="OPTIMIZE_SPACE_INVALID"):
    """把候选值收敛到参数类型并做 PARAM_META 区间校验；返回 (canonical, err)。"""
    meta = meta if isinstance(meta, dict) else {}
    typ = str(meta.get("type") or (type(default).__name__ if default is not None else ""))
    if typ in ("int", "float"):
        if isinstance(value, bool):
            return None, f"{prefix}: {key}={value!r} 需要数字"
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None, f"{prefix}: {key}={value!r} 需要数字"
        if not math.isfinite(num):
            return None, f"{prefix}: {key}={value!r} 需要有限数字"
        if typ == "int":
            if not num.is_integer():
                return None, f"{prefix}: {key}={value!r} 需要整数"
            num = int(num)
        if meta.get("min") is not None and num < float(meta["min"]):
            return None, f"{prefix}: {key}={value!r} 低于下限 {meta['min']}"
        if meta.get("max") is not None and num > float(meta["max"]):
            return None, f"{prefix}: {key}={value!r} 高于上限 {meta['max']}"
        return num, ""
    if typ == "bool":
        if isinstance(value, bool):
            return value, ""
        s = str(value).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True, ""
        if s in ("0", "false", "no", "off"):
            return False, ""
        return None, f"{prefix}: {key}={value!r} 需要布尔"
    if typ in ("str", "string"):
        return str(value), ""
    return value, ""


def _range_values(key, spec, default, meta):
    """{min,max,step} → 升序候选值。"""
    if "min" not in spec or "max" not in spec:
        return None, f"OPTIMIZE_SPACE_INVALID: {key} 的 range 需要 min 和 max"
    try:
        lo, hi = float(spec["min"]), float(spec["max"])
    except (TypeError, ValueError):
        return None, f"OPTIMIZE_SPACE_INVALID: {key} 的 min/max 需要数字"
    if hi < lo:
        return None, f"OPTIMIZE_SPACE_INVALID: {key} 的 max 不能小于 min"
    if hi == lo:
        return [lo], None
    typ = str((meta or {}).get("type")
              or (type(default).__name__ if default is not None else "float"))
    if spec.get("step") is not None:
        try:
            step = float(spec["step"])
        except (TypeError, ValueError):
            return None, f"OPTIMIZE_SPACE_INVALID: {key} 的 step 需要数字"
        if step <= 0:
            return None, f"OPTIMIZE_SPACE_INVALID: {key} 的 step 必须 > 0"
    elif typ == "int":
        step = 1.0
    else:
        step = (hi - lo) / 10.0
        if step <= 0:
            step = 1.0
    n = int(math.floor((hi - lo) / step + 1e-9)) + 1
    if n > MAX_SPACE_VALUES:
        return None, (f"OPTIMIZE_SPACE_TOO_LARGE: {key} 按 step={step} 生成 {n} 个候选值，"
                      f"超过上限 {MAX_SPACE_VALUES}（调大 step 或改 values）")
    vals = [round(lo + i * step, 10) for i in range(n)]
    if typ == "int":
        vals = [int(round(v)) for v in vals]
    return vals, None


def parse_space(info, space, prefix_cast="OPTIMIZE_SPACE_INVALID"):
    """校验空间并展开为 {参数: [候选值]}。

    返回 (out, err)：out={"values": {k:[...]}, "base": {...}, "meta": {...}, "size": N}
    """
    base = dict((info or {}).get("params") or {})
    meta = dict((info or {}).get("param_meta") or {})
    if not isinstance(space, dict) or not space:
        return None, "OPTIMIZE_SPACE_EMPTY: 至少给一个参数候选（range 或 values）"
    unknown = [k for k in space if k not in base]
    if unknown:
        return None, (f"OPTIMIZE_SPACE_INVALID: 未知参数 {unknown}"
                      f"（可用: {list(base) or '无'}）")
    values = {}
    for key, spec in space.items():
        default = base.get(key)
        pmeta = meta.get(key) or {}
        if isinstance(spec, (list, tuple)):
            raw = list(spec)
        elif isinstance(spec, dict):
            extra = [k for k in spec if k not in ("min", "max", "step", "values")]
            if extra:
                return None, f"OPTIMIZE_SPACE_INVALID: {key} 不认识的键 {extra}"
            if "values" in spec and ("min" in spec or "max" in spec):
                return None, f"OPTIMIZE_SPACE_INVALID: {key} 的 values 与 min/max 只能二选一"
            if "values" in spec:
                raw = spec["values"]
                if not isinstance(raw, list):
                    return None, f"OPTIMIZE_SPACE_INVALID: {key}.values 需要数组"
            else:
                raw, err = _range_values(key, spec, default, pmeta)
                if err:
                    return None, err
        else:
            raw = [spec]
        if not raw:
            return None, f"OPTIMIZE_SPACE_EMPTY: {key} 的候选值不能为空"
        if len(raw) > MAX_SPACE_VALUES:
            return None, (f"OPTIMIZE_SPACE_TOO_LARGE: {key} 给了 {len(raw)} 个候选值，"
                          f"超过上限 {MAX_SPACE_VALUES}")
        vals = []
        for v in raw:
            val, err = cast_value(key, v, default, pmeta, prefix=prefix_cast)
            if err:
                return None, err
            if val not in vals:      # 去重且保序（5 与 5.0 视为同一值）
                vals.append(val)
        values[key] = vals
    size = 1
    for vals in values.values():
        size *= len(vals)
    return {"values": values, "base": base, "meta": meta, "size": size}, None


# ---------------------------------------------------------------- 目标/约束
def parse_objective(objective):
    if objective is None:
        return dict(DEFAULT_OBJECTIVE), None
    if isinstance(objective, str):
        objective = {"metric": objective}
    if not isinstance(objective, dict):
        return None, "OPTIMIZE_OBJECTIVE_INVALID: objective 需要对象 {metric,direction}"
    extra = [k for k in objective if k not in ("metric", "direction")]
    if extra:
        return None, f"OPTIMIZE_OBJECTIVE_INVALID: 不认识的键 {extra}"
    metric = str(objective.get("metric") or DEFAULT_OBJECTIVE["metric"])
    if metric not in METRIC_DIRECTIONS:
        return None, (f"OPTIMIZE_OBJECTIVE_INVALID: metric 需为 "
                      f"{'/'.join(METRIC_DIRECTIONS)}，收到 {metric!r}")
    direction = str(objective.get("direction") or METRIC_DIRECTIONS[metric]).lower()
    if direction not in ("max", "min"):
        return None, "OPTIMIZE_OBJECTIVE_INVALID: direction 需为 max 或 min"
    return {"metric": metric, "direction": direction}, None


def parse_constraints(constraints):
    if constraints is None:
        return {}, None
    if not isinstance(constraints, dict):
        return None, "OPTIMIZE_CONSTRAINT_INVALID: constraints 需要对象"
    extra = [k for k in constraints if k not in ("min_trades", "max_drawdown")]
    if extra:
        return None, f"OPTIMIZE_CONSTRAINT_INVALID: 不认识的键 {extra}"
    out = {}
    if constraints.get("min_trades") is not None:
        try:
            n = int(constraints["min_trades"])
        except (TypeError, ValueError):
            return None, "OPTIMIZE_CONSTRAINT_INVALID: min_trades 需要整数"
        if n < 0:
            return None, "OPTIMIZE_CONSTRAINT_INVALID: min_trades 不能为负"
        out["min_trades"] = n
    if constraints.get("max_drawdown") is not None:
        try:
            d = float(constraints["max_drawdown"])
        except (TypeError, ValueError):
            return None, "OPTIMIZE_CONSTRAINT_INVALID: max_drawdown 需要数字"
        if not (0 < d <= 1):
            return None, "OPTIMIZE_CONSTRAINT_INVALID: max_drawdown 需在 (0,1]（如 0.3=回撤不超 30%）"
        out["max_drawdown"] = d
    return out, None


def score_stats(stats, objective, constraints):
    """给一次试次评分：{status, score, value, reason}。

    status=ok / rejected（约束）/ invalid（指标缺失）。
    score 统一成“越大越好”（direction=min 时取负），便于排序。
    """
    stats = stats if isinstance(stats, dict) else {}
    metric = objective["metric"]
    value = stats.get(metric)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return {"status": "invalid", "score": None, "value": None,
                "reason": f"METRIC_UNAVAILABLE: {metric} 无有效值"}
    if not math.isfinite(value):
        return {"status": "invalid", "score": None, "value": None,
                "reason": f"METRIC_UNAVAILABLE: {metric} 非有限数"}
    cons = constraints or {}
    if "min_trades" in cons:
        try:
            trades = int(stats.get("trade_count") or 0)
        except (TypeError, ValueError):
            trades = 0
        if trades < cons["min_trades"]:
            return {"status": "rejected", "score": None, "value": value,
                    "reason": f"MIN_TRADES: 交易 {trades} < {cons['min_trades']}"}
    if "max_drawdown" in cons:
        mdd = stats.get("max_drawdown")
        try:
            mdd = abs(float(mdd))
        except (TypeError, ValueError):
            mdd = 1.0
        if mdd > cons["max_drawdown"] + 1e-12:
            return {"status": "rejected", "score": None, "value": value,
                    "reason": f"MAX_DRAWDOWN: 回撤 {mdd:.2%} > {cons['max_drawdown']:.2%}"}
    score = value if objective["direction"] == "max" else -value
    return {"status": "ok", "score": score, "value": value, "reason": ""}


# ---------------------------------------------------------------- 搜索器
def expand_grid(values, limit):
    """全组合展开；超过预算直接拒绝（让用户改小空间或换 random/bayes）。"""
    keys = list(values)
    total = 1
    for k in keys:
        total *= len(values[k])
    if total > limit:
        return None, (f"OPTIMIZE_BUDGET: 网格共有 {total} 组，超过预算 {limit}"
                      f"（改小空间或换 random/bayes）")
    return [dict(zip(keys, combo)) for combo in itertools.product(*[values[k] for k in keys])], None


def random_candidate(values, rng):
    return {k: rng.choice(vals) for k, vals in values.items()}


def next_random(values, rng, tried):
    """下一个未尝试的随机候选；空间用尽返回 None。"""
    return _random_untried(values, rng, tried)


def random_unique(values, rng, tried, budget):
    """均匀采样不重复候选；空间小于预算时提前用尽。"""
    out = []
    attempts = 0
    max_attempts = max(200, budget * 40)
    while len(out) < budget and attempts < max_attempts:
        attempts += 1
        c = random_candidate(values, rng)
        key = _key(c)
        if key in tried:
            continue
        tried.add(key)
        out.append(c)
    return out


def _key(params):
    return tuple(sorted((k, repr(v)) for k, v in params.items()))


def _distribution(observations, key, vals):
    counts = Counter(o["params"].get(key) for o in observations)
    weights = [counts.get(v, 0) + 1.0 for v in vals]   # 平滑：没出现过的值也有机会
    return weights, sum(weights)


def propose_tpe(values, observations, rng, tried, attempts=200):
    """内置 TPE-lite：从“好组”分布采样，按好/坏联合密度比接受；无解返回 None。

    observations: [{"params": {...}, "score": float}]，只含 score 有效的试次。
    """
    obs = [o for o in observations if o.get("score") is not None]
    if len(obs) < 2:
        return _random_untried(values, rng, tried)
    ranked = sorted(obs, key=lambda o: o["score"], reverse=True)
    n_good = max(1, int(math.ceil(len(ranked) * 0.25)))
    n_good = min(n_good, len(ranked) - 1)
    good, bad = ranked[:n_good], ranked[n_good:]
    for _ in range(attempts):
        proposal, log_pg, log_pb = {}, 0.0, 0.0
        for key, vals in values.items():
            wg, sg = _distribution(good, key, vals)
            wb, sb = _distribution(bad, key, vals)
            i = _weighted_index(wg, rng)
            v = vals[i]
            proposal[key] = v
            log_pg += math.log(wg[i] / sg)
            log_pb += math.log(wb[i] / sb)
        if _key(proposal) in tried:
            continue
        diff = log_pg - log_pb
        accept = 1.0 if diff >= 0 else math.exp(diff)
        if rng.random() <= accept:
            return proposal
    return _random_untried(values, rng, tried)


def _weighted_index(weights, rng):
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for i, w in enumerate(weights):
        acc += w
        if r <= acc:
            return i
    return len(weights) - 1


def _random_untried(values, rng, tried, attempts=300):
    for _ in range(attempts):
        c = random_candidate(values, rng)
        if _key(c) not in tried:
            return c
    return None


# ---------------------------------------------------------------- 切分/排序/报告
def split_eval_bars(n_eval, ratio, min_eval=MIN_EVAL_BARS):
    """样本内/外可评估根数；ratio=0 表示不切。返回 (is_n, oos_n, err)。"""
    try:
        ratio = float(ratio or 0)
    except (TypeError, ValueError):
        return None, None, "OPTIMIZE_HOLDOUT_INVALID: ratio 需要数字"
    if ratio < 0 or ratio > 0.5:
        return None, None, "OPTIMIZE_HOLDOUT_INVALID: ratio 需在 0~0.5（0=不做样本外）"
    if ratio == 0:
        return int(n_eval), 0, None
    is_n = int(n_eval * (1.0 - ratio))
    oos_n = int(n_eval) - is_n
    if is_n < min_eval or oos_n < min_eval:
        return None, None, (f"OPTIMIZE_HOLDOUT_TOO_SMALL: 可评估 {n_eval} 根，"
                            f"切出样本内 {is_n} / 样本外 {oos_n}，各需至少 {min_eval} 根")
    return is_n, oos_n, None


def select_top(trials, k):
    ok = [t for t in trials if t.get("status") == "ok" and t.get("score") is not None]
    ok.sort(key=lambda t: (-float(t["score"]), int(t.get("index") or 0)))
    return ok[:max(0, int(k))]


def overfit_check(is_stats, oos_stats, objective):
    """返回 {gap, ratio, warnings}；warnings 是 [{code,message}]。"""
    metric = objective["metric"]
    is_v = _num((is_stats or {}).get(metric))
    oos_v = _num((oos_stats or {}).get(metric))
    out = {"gap": None, "ratio": None, "warnings": []}
    if is_v is not None and oos_v is not None:
        out["gap"] = oos_v - is_v
        if abs(is_v) > 1e-12:
            out["ratio"] = oos_v / is_v
    if oos_v is None:
        out["warnings"].append({"code": "OOS_INVALID",
                                "message": f"样本外没有有效的 {metric}，无法验证"})
        return out
    # max_drawdown 恒为负，“没有正收益”这条不适用
    if metric != "max_drawdown":
        direction = objective["direction"]
        edge = oos_v if direction == "max" else -oos_v
        if edge <= 0:
            out["warnings"].append({"code": "OOS_NO_EDGE",
                                    "message": f"样本外 {metric}={oos_v:.4g}，没有正优势"})
        if is_v is not None:
            is_edge = is_v if direction == "max" else -is_v
            oos_edge = edge
            if is_edge > 0 and oos_edge < is_edge * 0.5:
                out["warnings"].append({"code": "OOS_DEGRADED",
                                        "message": (f"样本外 {metric} 只有样本内的 "
                                                    f"{(oos_edge / is_edge):.0%}，可能过拟合")})
    return out


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def summarize_trial(index, params, result, objective, constraints):
    """把 _execute_run 的返回收敛成报告里的试次行。"""
    stats = ((result or {}).get("result") or {}).get("stats") or {}
    scored = score_stats(stats, objective, constraints)
    return {
        "index": index,
        "params": params,
        "status": scored["status"],
        "score": scored["score"],
        "value": scored["value"],
        "reason": scored["reason"],
        "is_stats": stats,
        "runtime_ms": ((result or {}).get("run") or {}).get("elapsed_ms"),
    }
