"""v0.6.5 参数寻优内核（纯函数，不依赖 numpy/optuna）；v0.6.7 增 WF 切窗/参数邻域。

设计要点（定稿见 docs/0.6.5-参数寻优方案.md）：
- 空间 = 每个参数一组离散候选值（range 或 values），统一收敛到参数类型；
- 搜索器已插件化（v0.6.6）：grid/random/bayes 在 scripts/optimizer/ 内置脚本；
- 本模块保留空间解析/评分/切分/过拟合与 TPE-lite 纯函数，供内置脚本复用；
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


def _check_constraints(stats, constraints):
    """返回 (ok, reason)；约束不满足时 ok=False。"""
    cons = constraints or {}
    stats = stats if isinstance(stats, dict) else {}
    if "min_trades" in cons:
        try:
            trades = int(stats.get("trade_count") or 0)
        except (TypeError, ValueError):
            trades = 0
        if trades < cons["min_trades"]:
            return False, f"MIN_TRADES: 交易 {trades} < {cons['min_trades']}"
    if "max_drawdown" in cons:
        mdd = stats.get("max_drawdown")
        try:
            mdd = abs(float(mdd))
        except (TypeError, ValueError):
            mdd = 1.0
        if mdd > cons["max_drawdown"] + 1e-12:
            return False, f"MAX_DRAWDOWN: 回撤 {mdd:.2%} > {cons['max_drawdown']:.2%}"
    return True, ""


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
    ok, reason = _check_constraints(stats, constraints)
    if not ok:
        return {"status": "rejected", "score": None, "value": value, "reason": reason}
    score = value if objective["direction"] == "max" else -value
    return {"status": "ok", "score": score, "value": value, "reason": ""}


def score_multi(stats, constraints):
    """多目标/自定义排序模式：只做约束判定，不强行合成单指标分数。"""
    ok, reason = _check_constraints(stats, constraints)
    return {"status": "ok" if ok else "rejected", "score": None,
            "value": None, "reason": reason}


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


def summarize_trial(index, params, result, objective, constraints, multi=False):
    """把 _execute_run 的返回收敛成报告里的试次行。"""
    stats = ((result or {}).get("result") or {}).get("stats") or {}
    scored = score_multi(stats, constraints) if multi else score_stats(stats, objective, constraints)
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


# ================================================================
# v0.6.7 稳健性：walk-forward 切窗 + 参数邻域
# ================================================================

DEFAULT_WALK_FORWARD = {
    "folds": 5,
    "window": "rolling",
    "is_ratio": 0.75,
    "step": None,
    "min_oos_bars": MIN_EVAL_BARS,
    "top_k": 1,
}
DEFAULT_STABILITY = {
    "enabled": True,
    "mode": "auto",
    "radius": 1,
    "scope": "one_at_a_time",
    "max_runs": 24,
    "pass_ratio": 0.5,
    "plateau_ratio": 0.8,
}


def _cfg_int(value, name, lo, hi):
    try:
        if isinstance(value, bool):
            raise ValueError
        n = int(value)
    except (TypeError, ValueError):
        return None, f"WF_CONFIG_INVALID: {name} 需要整数"
    if n < lo or n > hi:
        return None, f"WF_CONFIG_INVALID: {name} 需在 {lo}~{hi}"
    return n, None


def build_walk_forward(n_eval, config=None, min_eval=MIN_EVAL_BARS):
    """把可评估根数切成 fold_count 个 IS/OOS 窗口（相对 eval_idx 的索引）。

    每个 fold 的 OOS 紧接 IS，默认 step=OOS 长度（OOS 不重叠）；
    rolling 的 IS 起点每折前移 step，anchored 的 IS 起点固定、长度递增。
    数据不够时从请求折数逐级降到 3 折；仍不够返回 WF_INSUFFICIENT_BARS。
    """
    cfg = dict(config or {})
    allowed = set(DEFAULT_WALK_FORWARD)
    extra = [k for k in cfg if k not in allowed]
    if extra:
        return None, f"WF_CONFIG_INVALID: 不认识的键 {extra}"
    folds_req, err = _cfg_int(cfg.get("folds", DEFAULT_WALK_FORWARD["folds"]),
                              "folds", 3, 10)
    if err:
        return None, err
    top_k, err = _cfg_int(cfg.get("top_k", DEFAULT_WALK_FORWARD["top_k"]),
                          "top_k", 1, 3)
    if err:
        return None, err
    try:
        is_ratio = float(cfg.get("is_ratio", DEFAULT_WALK_FORWARD["is_ratio"]))
    except (TypeError, ValueError):
        return None, "WF_CONFIG_INVALID: is_ratio 需要数字"
    if not (0.5 <= is_ratio <= 0.9):
        return None, "WF_CONFIG_INVALID: is_ratio 需在 0.5~0.9（0.75=3:1）"
    min_oos, err = _cfg_int(cfg.get("min_oos_bars", DEFAULT_WALK_FORWARD["min_oos_bars"]),
                             "min_oos_bars", max(min_eval, 5), 5000)
    if err:
        return None, err
    window = str(cfg.get("window", DEFAULT_WALK_FORWARD["window"]) or "rolling").lower()
    if window not in ("rolling", "anchored"):
        return None, "WF_CONFIG_INVALID: window 需为 rolling 或 anchored"
    step_in = cfg.get("step", DEFAULT_WALK_FORWARD["step"])
    step = None
    if step_in is not None:
        step, err = _cfg_int(step_in, "step", 1, 100000)
        if err:
            return None, err

    try:
        n_eval = int(n_eval)
    except (TypeError, ValueError):
        return None, "WF_INSUFFICIENT_BARS: 可评估根数不是整数"
    if n_eval < max(min_eval * 3, min_oos * 3):
        need = int(math.ceil((min_eval / (1.0 - is_ratio)) + min_oos)) * 3
        return None, (f"WF_INSUFFICIENT_BARS: 可评估 {n_eval} 根，至少需要约 "
                      f"{need} 根（3 折 × 每折 OOS≥{min_oos}）")

    r = is_ratio / (1.0 - is_ratio)
    chosen = None
    for f in range(folds_req, 2, -1):
        if step is None:
            o = int(math.floor(n_eval / (r + f) + 1e-9))
            st = o
        else:
            st = step
            o = int(math.floor((n_eval - (f - 1) * st) / (r + 1.0) + 1e-9))
        while o >= min_oos:
            i = int(math.floor(r * o + 1e-9))
            end = i + (f - 1) * st + o
            if i >= min_eval and st >= o and end <= n_eval:
                chosen = (f, i, o, st, end)
                break
            o -= 1
        if chosen:
            break
    if not chosen:
        need = int(math.ceil((r + 3) * min_oos))
        return None, (f"WF_INSUFFICIENT_BARS: 可评估 {n_eval} 根，按 "
                      f"IS:OOS={is_ratio:.0%}:{1 - is_ratio:.0%} 切不出 3 折；"
                      f"至少需要约 {need} 根（或调小 min_oos_bars）")

    f, i, o, st, end = chosen
    warnings = []
    if f < folds_req:
        warnings.append({
            "code": "WF_FOLDS_REDUCED",
            "message": (f"数据只够 {f} 折，已从请求的 {folds_req} 折自动降低；"
                        f"每折 IS {i} 根 / OOS {o} 根"),
        })
    if st > o:
        warnings.append({
            "code": "WF_STEP_GAP",
            "message": f"step={st} 大于 OOS={o}，相邻测试段之间有 {st - o} 根空档",
        })
    unused = n_eval - end
    windows = []
    for k in range(f):
        is_start = (k * st) if window == "rolling" else 0
        is_end = i + k * st
        oos_start = is_end
        oos_end = oos_start + o
        windows.append({
            "index": k,
            "is_start": is_start, "is_end": is_end,
            "oos_start": oos_start, "oos_end": oos_end,
            "is_bars": (i + k * st) if window == "anchored" else i,
            "oos_bars": o,
        })
    return {
        "folds_requested": folds_req, "fold_count": f, "top_k": top_k,
        "window": window, "is_ratio": is_ratio,
        "is_bars": i, "oos_bars": o, "step_bars": st,
        "unused_bars": max(0, unused), "windows": windows,
        "warnings": warnings,
    }, None


def parse_stability(config):
    """校验参数邻域配置；返回 (cfg, err)。"""
    cfg = dict(config or {})
    allowed = set(DEFAULT_STABILITY)
    extra = [k for k in cfg if k not in allowed]
    if extra:
        return None, f"STABILITY_CONFIG_INVALID: 不认识的键 {extra}"
    out = dict(DEFAULT_STABILITY)
    out.update(cfg)
    if not isinstance(out.get("enabled"), bool):
        return None, "STABILITY_CONFIG_INVALID: enabled 需要布尔"
    mode = str(out["mode"] or "auto").lower()
    if mode not in ("auto", "step", "percent"):
        return None, "STABILITY_CONFIG_INVALID: mode 需为 auto/step/percent"
    out["mode"] = mode
    scope = str(out["scope"] or "one_at_a_time").lower()
    if scope not in ("one_at_a_time", "top2", "full"):
        return None, "STABILITY_CONFIG_INVALID: scope 需为 one_at_a_time/top2/full"
    out["scope"] = scope
    radius, err = _cfg_int(out["radius"], "radius", 1, 2)
    if err:
        return None, err
    max_runs, err = _cfg_int(out["max_runs"], "max_runs", 2, 100)
    if err:
        return None, err
    try:
        pass_ratio = float(out["pass_ratio"])
        plateau_ratio = float(out["plateau_ratio"])
    except (TypeError, ValueError):
        return None, "STABILITY_CONFIG_INVALID: pass_ratio/plateau_ratio 需要数字"
    if not (0.1 <= pass_ratio <= 0.9):
        return None, "STABILITY_CONFIG_INVALID: pass_ratio 需在 0.1~0.9"
    if not (0.1 <= plateau_ratio <= 1.0):
        return None, "STABILITY_CONFIG_INVALID: plateau_ratio 需在 0.1~1.0"
    out.update({"radius": radius, "max_runs": max_runs,
                "pass_ratio": pass_ratio, "plateau_ratio": plateau_ratio})
    return out, None


def _neighbor_values(values, center, meta, mode, radius):
    """单个参数的邻域候选：离散空间按索引 ±半径，连续空间按 ±10%。"""
    vals = list(values or [])
    if len(vals) <= 1:
        return []
    typ = str((meta or {}).get("type") or type(center).__name__)
    if typ not in ("int", "float"):
        return []
    mode = mode if mode in ("step", "percent") else ("step" if typ == "int" else "percent")
    if mode == "step":
        try:
            idx = vals.index(center)
        except ValueError:
            idx = min(range(len(vals)), key=lambda j: abs(float(vals[j]) - float(center)))
        out = []
        for d in range(-radius, radius + 1):
            j = idx + d
            if d and 0 <= j < len(vals) and vals[j] not in out:
                out.append(vals[j])
        return out
    # percent：先按 ±10% 算目标，再吸附到最近的离散候选值；整数至少 1 步
    try:
        base = float(center)
    except (TypeError, ValueError):
        base = 0.0
    pct = 0.1
    step0 = abs(base) * pct
    raw_step = (meta or {}).get("step")
    try:
        if raw_step is not None and float(raw_step) > 0:
            step0 = max(step0, float(raw_step))
    except (TypeError, ValueError):
        pass
    if typ == "int":
        step0 = max(1.0, round(step0))
    out = []
    for d in (-1, 1):
        target = base + d * step0 * max(1, radius)
        near = min(vals, key=lambda v: abs(float(v) - target))
        if near != center and near not in out:
            out.append(near)
    return out


def build_neighbors(values, center, meta, config=None):
    """围绕 center 生成邻域候选（含 center 本身）。

    one_at_a_time：每个参数单独动，其余固定（默认，1+2P 次）；
    top2：前两个参数做二维网格；full：全部参数笛卡尔积（受 max_runs 截断）。
    """
    cfg, err = parse_stability(config)
    if err:
        return None, err
    values = values or {}
    center = center or {}
    base = {k: center.get(k, (vals[0] if vals else None)) for k, vals in values.items()}
    neighbor = {}
    for k, vals in values.items():
        neighbor[k] = _neighbor_values(vals, base[k], (meta or {}).get(k) or {},
                                       cfg["mode"], cfg["radius"])
    keys = [k for k in values if neighbor.get(k)]
    candidates = [dict(base)]

    def add(cand):
        if all(cand.get(k) == base.get(k) for k in values):
            return
        key = _key(cand)
        if key not in seen:
            seen.add(key)
            candidates.append(cand)

    seen = {_key(base)}
    if cfg["scope"] == "one_at_a_time" or not keys:
        for k in keys:
            for v in neighbor[k]:
                c = dict(base)
                c[k] = v
                add(c)
    elif cfg["scope"] == "top2":
        top = keys[:2]
        if len(top) == 1:
            for v in neighbor[top[0]]:
                c = dict(base)
                c[top[0]] = v
                add(c)
        else:
            for a in [base[top[0]]] + neighbor[top[0]]:
                for b in [base[top[1]]] + neighbor[top[1]]:
                    c = dict(base)
                    c[top[0]], c[top[1]] = a, b
                    add(c)
    else:
        pools = [[base[k]] + neighbor[k] for k in keys]
        for combo in itertools.product(*pools):
            c = dict(base)
            c.update(dict(zip(keys, combo)))
            add(c)
            if len(candidates) >= cfg["max_runs"]:
                break
    return candidates[:cfg["max_runs"]], None


def stability_summary(runs, center, pass_ratio=0.5, plateau_ratio=0.8):
    """邻域结果 → 稳定分/孤峰判定；runs 里用 oos_score 排序（越大越好）。"""
    valid = [r for r in (runs or []) if r.get("oos_score") is not None]
    out = {
        "runs": len(runs or []), "valid": len(valid),
        "pass_ratio": 0.0, "plateau_ratio": 0.0,
        "best_to_median": None, "isolated_peak": False,
        "center_is_best": False, "warnings": [],
    }
    if not valid:
        out["warnings"].append({"code": "STABILITY_NO_VALID",
                                "message": "邻域没有可评分的 OOS 试次"})
        return out
    best = max(float(r["oos_score"]) for r in valid)
    med = sorted(float(r["oos_score"]) for r in valid)[len(valid) // 2]
    margin_pass = abs(best) * (1.0 - float(pass_ratio))
    margin_plateau = abs(best) * (1.0 - float(plateau_ratio))
    passed = [r for r in valid if float(r["oos_score"]) >= best - margin_pass]
    plateau = [r for r in valid if float(r["oos_score"]) >= best - margin_plateau]
    out["pass_ratio"] = len(passed) / len(valid)
    out["plateau_ratio"] = len(plateau) / len(valid)
    out["best_to_median"] = (best / med) if abs(med) > 1e-12 else None
    ckey = _key(center or {})
    center_run = next((r for r in valid if _key(r.get("params") or {}) == ckey), None)
    out["center_is_best"] = bool(center_run and abs(float(center_run["oos_score"]) - best) < 1e-12)
    if len(valid) < 3:
        out["warnings"].append({"code": "STABILITY_FEW_RUNS",
                                "message": f"只有 {len(valid)} 个有效邻域，结论偏弱"})
    if out["pass_ratio"] < float(pass_ratio):
        out["isolated_peak"] = True
        out["warnings"].append({
            "code": "PARAM_ISOLATED_PEAK",
            "message": (f"仅 {out['pass_ratio']:.0%} 邻域达到最优的 "
                        f"{float(pass_ratio):.0%} 阈值，最优参数可能是孤峰"),
        })
    if center_run is None:
        out["warnings"].append({"code": "STABILITY_CENTER_MISSING",
                                "message": "中心参数没有有效 OOS 试次"})
    return out
