"""v0.6.0 结果实例：冻结记录、口径、校验、数据质量。

设计要点（对标 Vibe-Trading / QuantDinger 后定稿）：
- 结果 = 一次运行的冻结实验记录，重跑不覆盖，可改名可删除；
- 口径在结果层，不在某个引擎里：内置/外部/插件共用一份；
- 执行假设是结构化字段，不是人话列表（跨引擎可逐字段对比）；
- 数据指纹 + 质量 + 可复现哈希一起进结果，别让"结果对不对"靠猜；
- 大数组不进 summary，按 section 分页取。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone

SCHEMA = 1
MAX_RESULTS_PER_BOARD = 100
MAX_EQUITY_POINTS = 50000
MAX_TRADES = 5000
MAX_SOURCE_CHARS = 200_000

STATUSES = ("completed_trades", "open_position_only", "no_signals")

_TF_BARS_PER_YEAR = {
    "1m": 525600, "3m": 175200, "5m": 105120, "15m": 35040, "30m": 17520,
    "1h": 8760, "2h": 4380, "4h": 2190, "6h": 1460, "8h": 1095, "12h": 730,
    "1d": 365, "3d": 122, "1w": 52, "1M": 12,
}


def now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _num(v):
    """有限浮点；其余 None（NaN/Inf/字符串一律不当数字）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _to_ms(v):
    """秒/毫秒自适应；None 原样。"""
    if v is None:
        return None
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n * 1000 if abs(n) < 10**11 else n


def _sha_json(obj) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sha_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def bars_per_year(tf: str):
    """周期 → 年化 bar 数；未知周期给 None，让调用方显式传。"""
    if tf in _TF_BARS_PER_YEAR:
        return _TF_BARS_PER_YEAR[tf]
    m = re.match(r"^(\d+)([mhdwM])$", tf or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    minutes = n * {"m": 1, "h": 60, "d": 1440, "w": 10080, "M": 43200}[unit]
    return max(1, int(525600 / minutes))


def _stem(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_")
    return s[:32] or "ext"


def next_result_id(existing, strategy_id: str = "ext") -> str:
    head = f"bt_{_stem(str(strategy_id).split('/')[-1])}_"
    n = 1
    while f"{head}{n}" in existing:
        n += 1
    return f"{head}{n}"


# ============================ 口径 ============================

def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs):
    """样本标准差（ddof=1）；不足两个样本返回 0。"""
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _returns(values):
    return [values[i] / values[i - 1] - 1 for i in range(1, len(values))
            if values[i - 1] not in (0, None) and values[i] is not None]


def compute_stats(equity, trades, initial_cash, bpy=None, benchmark=None) -> dict:
    """结果口径全家桶。equity=[values]，trades=规范化 trades，benchmark={times,values}。"""
    values = [v for v in equity if v is not None]
    n = len(values)
    init = _num(initial_cash) or (values[0] if values else 0.0)
    out = {
        "final_value": values[-1] if values else init,
        "total_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0,
        "volatility": 0.0, "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0,
        "win_rate": 0.0, "profit_loss_ratio": None, "profit_factor": None,
        "max_consecutive_loss": 0, "trade_count": len(trades or []),
        "execution_count": None, "avg_holding_bars": 0.0, "exposure": 0.0,
        "total_fees": 0.0, "benchmark_return": None, "excess_return": None,
        "information_ratio": None, "tracking_error": None, "benchmark_beta": None,
    }
    if n == 0:
        return out

    total = (values[-1] / init - 1) if init else 0.0
    out["total_return"] = total
    periods = max(n - 1, 1)
    growth = 1 + total
    if growth <= 0:
        ann = -1.0
    else:
        try:
            ann = growth ** ((bpy or 365) / periods) - 1
        except OverflowError:
            ann = float("inf")
    out["annual_return"] = ann if math.isfinite(ann) else None

    rets = _returns(values)
    if len(rets) > 1:
        vol = _std(rets)
        out["volatility"] = vol * math.sqrt(bpy or 365)
        if vol > 1e-12:
            out["sharpe"] = _mean(rets) / vol * math.sqrt(bpy or 365)
        down = math.sqrt(sum(min(r, 0.0) ** 2 for r in rets) / len(rets))
        if down > 1e-12:
            out["sortino"] = _mean(rets) / down * math.sqrt(bpy or 365)
    if not math.isfinite(out["sharpe"] or 0):
        out["sharpe"] = 0.0
    if not math.isfinite(out["sortino"] or 0):
        out["sortino"] = 0.0

    peak = init
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            max_dd = min(max_dd, v / peak - 1)
    out["max_drawdown"] = max_dd
    if abs(max_dd) > 1e-12 and out["annual_return"] is not None:
        out["calmar"] = out["annual_return"] / abs(max_dd)
        if not math.isfinite(out["calmar"]):
            out["calmar"] = 0.0

    # 交易统计
    pnls = [_num(t.get("pnl")) for t in (trades or [])]
    pnls = [p for p in pnls if p is not None]
    if pnls:
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        out["win_rate"] = len(wins) / len(pnls)
        if losses:
            avg_win = _mean(wins) if wins else 0.0
            avg_loss = abs(_mean(losses))
            gross_loss = abs(sum(losses))
            if avg_loss > 1e-12:
                out["profit_loss_ratio"] = avg_win / avg_loss
            if gross_loss > 1e-12:
                out["profit_factor"] = (sum(wins) if wins else 0.0) / gross_loss
        consec = cur = 0
        for p in pnls:
            if p < 0:
                cur += 1
                consec = max(consec, cur)
            else:
                cur = 0
        out["max_consecutive_loss"] = consec
    holds = [_num(t.get("holding_bars")) for t in (trades or [])]
    holds = [h for h in holds if h is not None and h >= 0]
    if holds:
        out["avg_holding_bars"] = _mean(holds)
    fees = [_num(t.get("fee")) for t in (trades or [])]
    out["total_fees"] = sum(f for f in fees if f is not None)
    out["trade_count"] = len(trades or [])

    return out


def compute_stats_full(equity_times, equity_values, trades, initial_cash, bpy=None,
                       benchmark=None, fills=None) -> dict:
    """compute_stats 的完整入口（带时间轴，算暴露度与基准相对指标）。"""
    out = compute_stats(equity_values, trades, initial_cash, bpy, benchmark)
    n = len(equity_values)
    if fills is not None:
        out["execution_count"] = len(fills)

    # 暴露度
    if equity_times and trades:
        marks = [False] * len(equity_times)
        for t in trades:
            a = _to_ms(t.get("entry_time"))
            b = _to_ms(t.get("exit_time"))
            if a is None or b is None:
                continue
            i = bisect_left(equity_times, min(a, b))
            j = bisect_right(equity_times, max(a, b))
            for k in range(max(0, i), min(n, j)):
                marks[k] = True
        out["exposure"] = (sum(marks) / n) if n else 0.0

    # 缺 holding_bars 的用时间轴补
    if equity_times:
        for t in trades:
            if t.get("holding_bars") is None:
                a, b = _to_ms(t.get("entry_time")), _to_ms(t.get("exit_time"))
                if a is not None and b is not None:
                    t["holding_bars"] = max(0, bisect_left(equity_times, max(a, b))
                                             - bisect_left(equity_times, min(a, b)))

    # holding_bars 补齐后重算均值（compute_stats 在补齐前跑过）
    holds = [t.get("holding_bars") for t in trades
             if t.get("holding_bars") is not None and t.get("holding_bars") >= 0]
    out["avg_holding_bars"] = (sum(holds) / len(holds)) if holds else 0.0

    # 基准相对指标
    if benchmark and benchmark.get("values") and len(benchmark["values"]) > 1:
        bvals = benchmark["values"]
        out["benchmark_return"] = bvals[-1] / bvals[0] - 1 if bvals[0] else 0.0
        out["excess_return"] = out["total_return"] - out["benchmark_return"]
        bmap = dict(zip(benchmark.get("times") or [], bvals))
        pairs = []
        for i in range(1, len(equity_times)):
            ta, tb = equity_times[i - 1], equity_times[i]
            if ta in bmap and tb in bmap and bmap[ta] and equity_values[i - 1]:
                pairs.append((equity_values[i] / equity_values[i - 1] - 1,
                              bmap[tb] / bmap[ta] - 1))
        if len(pairs) > 1:
            active = [p[0] - p[1] for p in pairs]
            te = _std(active)
            out["tracking_error"] = te * math.sqrt(bpy or 365)
            if te > 1e-12:
                out["information_ratio"] = _mean(active) / te * math.sqrt(bpy or 365)
            bmean = _mean([p[1] for p in pairs])
            bvar = sum((p[1] - bmean) ** 2 for p in pairs) / (len(pairs) - 1)
            if bvar > 1e-15:
                cov = sum((p[0] - _mean([x[0] for x in pairs])) * (p[1] - bmean)
                          for p in pairs) / (len(pairs) - 1)
                out["benchmark_beta"] = cov / bvar
    return out


# ============================ 数据质量 ============================

def data_quality(bars, requested_from=None, requested_to=None, expected=None) -> dict:
    """对当前板已载入的 bars 做一次体检（0.6.0 用重叠段粗算）。"""
    bars = bars or []
    rf = _to_ms(requested_from) if requested_from is not None else None
    rt = _to_ms(requested_to) if requested_to is not None else None
    sel = [b for b in bars
           if (rf is None or _to_ms(b.get("timestamp")) >= rf)
           and (rt is None or _to_ms(b.get("timestamp")) <= rt)]
    count = len(sel)
    dup = 0
    gaps = 0
    zero = 0
    for i, b in enumerate(sel):
        hi, lo = _num(b.get("high")), _num(b.get("low"))
        if hi is not None and lo is not None and hi <= lo:
            zero += 1
        if i:
            prev = _to_ms(sel[i - 1].get("timestamp")) or 0
            cur = _to_ms(b.get("timestamp")) or 0
            if cur <= prev:
                dup += 1
    diffs = []
    for i in range(1, count):
        d = (_to_ms(sel[i].get("timestamp")) or 0) - (_to_ms(sel[i - 1].get("timestamp")) or 0)
        if d > 0:
            diffs.append(d)
    if len(diffs) >= 3:
        ds = sorted(diffs)
        med = ds[len(ds) // 2]
        gaps = sum(1 for d in diffs if med and d > med * 2.5)
    actual_from = _to_ms(sel[0].get("timestamp")) if sel else None
    actual_to = _to_ms(sel[-1].get("timestamp")) if sel else None
    coverage = (count / expected) if expected else None
    if count == 0:
        verdict = "bad"
    elif dup or zero:
        verdict = "bad"
    elif gaps or (coverage is not None and coverage < 0.99):
        verdict = "warn"
    else:
        verdict = "ok"
    notes = []
    if count == 0:
        notes.append("窗口内没有已载入的 K 线")
    if dup:
        notes.append(f"{dup} 根时间戳不递增")
    if gaps:
        notes.append(f"{gaps} 处间隔超过中位数的 2.5 倍")
    if zero:
        notes.append(f"{zero} 根 high<=low")
    if coverage is not None and coverage < 0.99:
        notes.append(f"窗口只覆盖 {coverage:.0%}（{count}/{expected} 根），部分区间未载入")
    return {
        "requested": {"from": rf, "to": rt},
        "actual": {"from": actual_from, "to": actual_to, "bars": count},
        "coverage": coverage,
        "gaps": gaps, "duplicates": dup, "zero_range_bars": zero,
        "verdict": verdict, "notes": notes,
    }


# ============================ 规范化 ============================

def _norm_equity(eq):
    """支持 {times,values|equity} / [{time,value}] / [[t,v]]；返回 (times, values) 或 (None, err)。"""
    times, values = None, None
    if isinstance(eq, dict):
        times = eq.get("times")
        values = eq.get("values", eq.get("equity"))
    elif isinstance(eq, list):
        if eq and isinstance(eq[0], dict):
            times = [_to_ms(x.get("time", x.get("timestamp"))) for x in eq]
            values = [x.get("value", x.get("equity")) for x in eq]
        elif eq and isinstance(eq[0], (list, tuple)) and len(eq[0]) >= 2:
            times = [_to_ms(x[0]) for x in eq]
            values = [x[1] for x in eq]
    if not isinstance(times, list) or not isinstance(values, list):
        return None, None, "RESULT_INVALID: equity 需要 {times[], values[]} 或 [[t,v],...]"
    if len(times) != len(values):
        return None, None, "RESULT_INVALID: equity.times 与 equity.values 长度不一致"
    if len(times) == 0:
        return None, None, "RESULT_INVALID: equity 为空"
    if len(times) > MAX_EQUITY_POINTS:
        return None, None, f"RESULT_LIMIT: equity 超过 {MAX_EQUITY_POINTS} 点"
    tout, vout = [], []
    last = None
    for t, v in zip(times, values):
        tm = _to_ms(t)
        fv = _num(v)
        if tm is None or fv is None:
            return None, None, "RESULT_INVALID: equity 含非法时间或非有限数值"
        if last is not None and tm <= last:
            return None, None, "RESULT_INVALID: equity.times 必须严格递增"
        last = tm
        tout.append(tm)
        vout.append(fv)
    return tout, vout, None


def _norm_trade(raw, idx):
    if not isinstance(raw, dict):
        return None
    g = lambda *ks: next((raw[k] for k in ks if raw.get(k) is not None), None)
    entry = _to_ms(g("entry_time", "entryTime", "open_time", "openTime"))
    exit_ = _to_ms(g("exit_time", "exitTime", "close_time", "closeTime"))
    ep, xp = _num(g("entry_price", "entryPrice", "open_price")), _num(g("exit_price", "exitPrice", "close_price"))
    size = _num(g("size", "quantity", "qty", "amount"))
    side = str(g("side", "direction") or "long").lower()
    if side in ("1", "buy", "b"):
        side = "long"
    if side in ("-1", "sell", "s"):
        side = "short"
    pnl = _num(g("pnl", "profit", "net_pnl"))
    fee = _num(g("fee", "commission", "fees")) or 0.0
    if pnl is None and ep is not None and xp is not None and size:
        sign = -1 if side == "short" else 1
        pnl = (xp - ep) * size * sign - fee
    pnl_pct = _num(g("pnl_pct", "profit_pct", "return_pct"))
    if pnl_pct is None and pnl is not None and ep and size:
        base = abs(ep * size)
        pnl_pct = pnl / base if base else None
    return {
        "id": str(g("id") or f"t{idx + 1}"),
        "side": side,
        "entry_time": entry, "exit_time": exit_,
        "entry_price": ep, "exit_price": xp,
        "size": size, "notional": _num(g("notional")) or ((ep * size) if ep and size else None),
        "gross_pnl": _num(g("gross_pnl")),
        "fee": fee,
        "pnl": pnl, "pnl_pct": pnl_pct,
        "entry_reason": str(g("entry_reason", "reason") or ""),
        "exit_reason": str(g("exit_reason", "close_reason") or ""),
        "holding_bars": _num(g("holding_bars", "holdingBars")),
    }


def _norm_fill(raw, idx):
    if not isinstance(raw, dict):
        return None
    g = lambda *ks: next((raw[k] for k in ks if raw.get(k) is not None), None)
    return {
        "id": str(g("id") or f"f{idx + 1}"),
        "time": _to_ms(g("time", "timestamp")),
        "action": str(g("action") or "fill"),
        "signed_qty": _num(g("signed_qty", "quantity", "size", "qty")),
        "price": _num(g("price", "execution_price")),
        "notional": _num(g("notional")),
        "fee": _num(g("fee", "commission")) or 0.0,
        "reason": str(g("reason") or ""),
    }


def normalize_result(payload, board_id, timeframe, bars=None, version="0.6.0",
                     source_sha256=None, symbol=None, source_script=None) -> dict:
    """校验 + 补算 + 冻结。返回 {result} 或 {error,warnings}。"""
    warnings = []
    if not isinstance(payload, dict):
        return {"error": "RESULT_INVALID: payload 需要 JSON 对象"}
    b_id = str(payload.get("board_id") or board_id or "")
    tf = str(payload.get("timeframe") or timeframe or "")
    if not b_id or not tf:
        return {"error": "RESULT_INVALID: 缺少 board_id/timeframe"}

    times, values, err = _norm_equity(payload.get("equity"))
    if err:
        return {"error": err, "warnings": warnings}

    raw_trades = payload.get("trades") or []
    if not isinstance(raw_trades, list):
        return {"error": "RESULT_INVALID: trades 需要数组"}
    if len(raw_trades) > MAX_TRADES:
        return {"error": f"RESULT_LIMIT: trades 超过 {MAX_TRADES} 条"}
    trades = [t for t in (_norm_trade(x, i) for i, x in enumerate(raw_trades)) if t]

    raw_fills = payload.get("fills")
    fills = None
    if isinstance(raw_fills, list):
        fills = [f for f in (_norm_fill(x, i) for i, x in enumerate(raw_fills)) if f]

    run_in = payload.get("run") if isinstance(payload.get("run"), dict) else {}
    initial_cash = _num(run_in.get("initial_cash", payload.get("initial_cash"))) or (
        values[0] if values else 10000.0)
    if abs(values[0] - initial_cash) > max(1e-6, abs(initial_cash) * 1e-6):
        return {"error": "RESULT_INVALID: equity[0] 必须等于初始资金，否则收益/回撤口径不成立"}

    bpy = _num(run_in.get("bars_per_year"))
    if bpy is None:
        bpy = bars_per_year(tf)
    if bpy is None:
        bpy = 365
        warnings.append("未知周期，年化按 365 bar/年计算")

    benchmark = None
    braw = payload.get("benchmark")
    if isinstance(braw, dict) and braw.get("values"):
        btimes = [_to_ms(x) for x in (braw.get("times") or [])]
        bvals = [x for x in (_num(v) for v in braw["values"]) if x is not None]
        if len(btimes) == len(bvals) and btimes:
            benchmark = {"id": str(braw.get("id") or "buy_hold"),
                         "times": btimes, "values": bvals}

    stats = compute_stats_full(times, values, trades, initial_cash, int(bpy),
                               benchmark, fills)
    declared = payload.get("stats") if isinstance(payload.get("stats"), dict) else None
    if declared:
        for key, tol in (("total_return", 1e-3), ("max_drawdown", 1e-3)):
            dv, cv = _num(declared.get(key)), _num(stats.get(key))
            if dv is not None and cv is not None and abs(dv - cv) > tol:
                warnings.append(f"调用方声明 {key}={dv:.4f} 与补算 {cv:.4f} 不一致，以补算为准")

    status = str(payload.get("status") or "")
    if status not in STATUSES:
        status = ("no_signals" if not (fills or trades)
                  else "open_position_only" if not trades else "completed_trades")

    data_in = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    req = data_in.get("requested") if isinstance(data_in.get("requested"), dict) else {}
    req_from = req.get("from") if req.get("from") is not None else times[0]
    req_to = req.get("to") if req.get("to") is not None else times[-1]
    width = data_quality(bars, req_from, req_to, expected=len(times))
    if width["verdict"] == "bad":
        warnings.append("数据质量检查未通过：" + "；".join(width["notes"]))

    # 执行假设：dict 原样；list 视为 notes
    assumptions = payload.get("execution_assumptions")
    if isinstance(assumptions, list):
        assumptions = {"notes": [str(x) for x in assumptions]}
    elif not isinstance(assumptions, dict):
        assumptions = {}
    assumptions = dict(assumptions)
    assumptions.setdefault("notes", [])
    for k in ("fill_rule", "bar_close_policy", "intrabar_mode", "funding_mode",
              "leverage", "lot_policy", "corporate_actions", "shorting"):
        assumptions.setdefault(k, None)

    engine = payload.get("engine") if isinstance(payload.get("engine"), dict) else {}
    engine = {
        "id": str(engine.get("id") or "external"),
        "version": str(engine.get("version") or ""),
        "license": str(engine.get("license") or ""),
        "caps": engine.get("caps") if isinstance(engine.get("caps"), dict) else {},
        "config": engine.get("config") if isinstance(engine.get("config"), dict) else {},
    }
    strategy = payload.get("strategy") if isinstance(payload.get("strategy"), dict) else {}
    src = strategy.get("source")
    src_text = str(src)[:MAX_SOURCE_CHARS] if isinstance(src, str) else ""
    strategy = {
        "id": str(strategy.get("id") or "strategy/unknown"),
        "mode": str(strategy.get("mode") or "signal"),
        "params": strategy.get("params") if isinstance(strategy.get("params"), dict) else {},
        "warmup": int(_num(strategy.get("warmup")) or 0),
        "protection": strategy.get("protection") if isinstance(strategy.get("protection"), dict) else {},
        "source_sha256": str(strategy.get("source_sha256") or (_sha_text(src_text) if src_text else "")),
        "source": src_text,
    }
    config_hash = _sha_json({"run": run_in, "params": strategy["params"],
                             "engine": engine["config"]})
    # 单位：由结果声明（股票=股/CNY，期货=手，币=BTC/USDT…），缺省为空，前端自行回退
    units_in = payload.get("units") if isinstance(payload.get("units"), dict) else {}
    units = {
        "quantity": str(units_in.get("quantity") or "")[:16].strip(),
        "currency": str(units_in.get("currency") or "")[:16].strip(),
    }
    repro_in = payload.get("reproducibility") if isinstance(payload.get("reproducibility"), dict) else {}
    reproducibility = {
        "agentkline_version": version,
        "config_hash": str(repro_in.get("config_hash") or config_hash),
        "strategy_source_sha256": strategy["source_sha256"],
        "data_source_sha256": str(source_sha256 or ""),
    }

    result = {
        "schema": SCHEMA,
        "result_id": str(payload.get("result_id") or ""),
        "display_name": str(payload.get("display_name") or strategy["id"].split("/")[-1] or "回测结果"),
        "created_at": int(payload.get("created_at") or now_ms()),
        "source": str(payload.get("source") or engine["id"]),
        "status": status,
        "runtime_ms": int(_num(payload.get("runtime_ms")) or 0),
        "engine": engine,
        "strategy": strategy,
        "run": {
            "initial_cash": initial_cash,
            "fee": _num(run_in.get("fee")) or 0.0,
            "slippage": _num(run_in.get("slippage")) or 0.0,
            "leverage": _num(run_in.get("leverage")) or 1.0,
            "bars_per_year": int(bpy),
            "window": {"from": times[0], "to": times[-1], "bars": len(times)},
        },
        "data": {
            "board": b_id, "timeframe": tf,
            "source_script": str(source_script or ""),
            "symbol": str(symbol or ""),
            "requested": width["requested"],
            "actual": width["actual"],
            "quality": width,
        },
        "stats": stats,
        "equity": {"times": times, "values": values},
        "trades": trades,
        "fills": fills or [],
        "benchmark": benchmark,
        "execution_assumptions": assumptions,
        "units": units,
        "reproducibility": reproducibility,
        "warnings": [str(x) for x in (payload.get("warnings") or []) if str(x).strip()] + warnings,
        "validation": payload.get("validation") if isinstance(payload.get("validation"), dict) else None,
    }
    return {"result": result, "warnings": warnings}


def summarize(result: dict) -> dict:
    """摘要：不含 equity/trades/fills/benchmark 大数组。"""
    out = {k: v for k, v in result.items()
           if k not in ("equity", "trades", "fills", "benchmark")}
    out["equity_points"] = len((result.get("equity") or {}).get("times") or [])
    out["trade_count"] = len(result.get("trades") or [])
    return out


def slice_section(result: dict, section: str = "summary", offset: int = 0, limit: int = 200) -> dict:
    """按 section 取数据；limit=0 表示全量。"""
    section = section or "summary"
    offset = max(0, int(offset or 0))
    limit = max(0, int(limit if limit is not None else 200))
    if section == "summary":
        return {"result": summarize(result)}
    if section == "equity":
        eq = result.get("equity") or {"times": [], "values": []}
        total = len(eq["times"])
        end = total if limit == 0 else min(total, offset + limit)
        return {"result_id": result["result_id"], "section": "equity",
                "times": eq["times"][offset:end], "values": eq["values"][offset:end],
                "total": total, "offset": offset, "returned": max(0, end - offset),
                "truncated": end < total, "next_offset": end if end < total else None}
    if section in ("trades", "fills"):
        items = result.get(section) or []
        total = len(items)
        end = total if limit == 0 else min(total, offset + limit)
        return {"result_id": result["result_id"], "section": section,
                "items": items[offset:end], "total": total, "offset": offset,
                "returned": max(0, end - offset),
                "truncated": end < total, "next_offset": end if end < total else None}
    return {"error": f"RESULT_INVALID: section 需为 summary/equity/trades/fills，收到 {section}"}
