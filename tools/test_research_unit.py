#!/usr/bin/env python3
"""研究闭环单测（0.6.4）：指纹与旧快照、运镜无浏览器语义。
无 pytest 依赖：python tools/test_research_unit.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentkline.core.service import AgentKlineService

ok = 0
bad = []


def check(name, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        bad.append(name)
        print(f"  ❌ {name} {detail}")


def main():
    svc = AgentKlineService(str(ROOT / "scripts"), data_dir=None)
    board = svc.create_board("t1", None, None, "BT/USDT", "datasource/mock_btc",
                             {"days": 300})
    check("mock 板就绪", board.get("id") == "t1" and board.get("source_lock"), str(board))

    # ---- 策略声明 ----
    info = svc.strategy_meta(script="strategy/ma_cross")
    check("策略声明可读", info.get("ok") and set((info.get("params") or {})) == {"fast", "slow"},
          str(info)[:120])

    # ---- 单跑：指纹 + 新鲜度 ----
    ctx = svc._run_context("t1", "1d", script="strategy/ma_cross", limit=300)
    check("窗口准备", not ctx.get("error"), str(ctx)[:120])
    body = svc._execute_run(ctx, {}, timeout=120)
    check("单跑产出结果", body.get("status") == "ok", str(body)[:200])
    rid = body["result"]["result_id"]
    summary = svc.get_result(rid, "summary")["result"]
    fp = (summary.get("data") or {}).get("fingerprint") or {}
    check("数据指纹落结果", fp.get("bars") == 300 and fp.get("head_close") is not None, str(fp))
    rows = svc.list_results("t1")
    fr = {r["result_id"]: r.get("freshness") for r in rows["results"]}
    check("同数据 → 不标旧快照", fr.get(rid) and fr[rid]["stale"] is False, str(fr.get(rid)))

    # 改尾价 → 旧快照
    bars = svc.state.get_ohlcv("t1", "1d")
    bars[-1]["close"] = float(bars[-1]["close"]) + 1.0
    rows2 = svc.list_results("t1")
    fr2 = {r["result_id"]: r.get("freshness") for r in rows2["results"]}
    check("尾价修订 → PRICE_REVISED",
          fr2.get(rid) and fr2[rid]["stale"] is True and fr2[rid]["reason"] == "PRICE_REVISED",
          str(fr2.get(rid)))

    # 窗口起点丢失 → HEAD_MOVED（删掉指纹起点那根）
    _bars = svc.state.get_ohlcv("t1", "1d")
    _i = next((i for i, b in enumerate(_bars) if int(b["timestamp"]) == int(fp["from"])), None)
    if _i is not None:
        _bars.pop(_i)
    rows3 = svc.list_results("t1")
    fr3 = {r["result_id"]: r.get("freshness") for r in rows3["results"]}
    check("起点丢失 → HEAD_MOVED",
          fr3.get(rid) and fr3[rid]["reason"] == "HEAD_MOVED", str(fr3.get(rid)))

    # ---- 运镜未连浏览器 ----
    out = svc.focus_result_trade(rid, 0)
    check("无浏览器 → NO_BROWSER", "NO_BROWSER" in str(out.get("error")), str(out))
    out2 = svc.focus_result_trade(rid, 999)
    check("trade_index 越界 → TRADE_NOT_FOUND", "TRADE_NOT_FOUND" in str(out2.get("error")), str(out2))

    print(f"\nResearch: {ok} passed, {len(bad)} failed")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
