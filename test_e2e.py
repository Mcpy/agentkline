#!/usr/bin/env python3
"""
AgentKline - 端到端测试脚本（v0.4 硬切版；打 agent 端口，需 Bearer token）
运行: python test_e2e.py [--port 8766] [--token <token>]
     token 也可用环境变量 AGENTKLINE_TOKEN 提供。
覆盖：建板即锁/板锁全等+SOURCE_LOCKED+suggestion/kline_source 幂等/poll_only/backfill 门控/
指标实例(inst_id/INST_EXISTS/BLOB_SCOPE/重算/过滤)/save_script 校验/搜索/护栏截断/
退役端点 404/MCP↔REST 两表面对齐断言/many 压测(save_script 10 参数)。
"""
import os
import sys
import json
import argparse
import sys
import requests

MCP_ONLY = {"take_snapshot"}  # 判决：刻意无 REST 触发
# MCP 工具 → REST 路由（method, path 子串）对齐表（防漂移断言用）
TOOL_REST_MAP = {
    "list_boards": ("get", "/api/boards"),
    "create_board": ("post", "/api/board"),
    "delete_board": ("delete", "/api/board/"),
    "switch_board": ("get", "/api/board/"),
    "list_timeframes": ("get", "/timeframes"),
    "create_timeframe": ("post", "/timeframe"),
    "delete_timeframe": ("delete", "/timeframe/"),
    "switch_timeframe": ("get", "/timeframe/"),
    "set_kline_source": ("put", "/kline_source"),
    "backfill": ("post", "/backfill"),
    "run_script": ("post", "/api/run-script"),
    "save_script": ("post", "/api/scripts"),
    "list_scripts": ("get", "/api/scripts"),
    "search_symbols": ("get", "/api/search"),
    "overview": ("get", "/api/overview"),
    "get_current_view": ("get", "/api/view"),
    "set_view_range": ("post", "/api/view/range"),
    "add_indicator": ("post", "/api/indicator"),
    "update_indicator": ("put", "/api/indicator/"),
    "delete_indicator": ("delete", "/api/indicator/"),
    "get_indicators": ("get", "/api/indicators"),
    "set_markers": ("post", "/api/markers"),
    "get_markers": ("get", "/api/markers"),
    "list_drawing_tools": ("get", "/api/drawing-tools"),
    "draw_drawing": ("post", "/api/drawing"),
    "draw_many": ("post", "/api/drawings"),
    "delete_drawings": ("post", "/api/drawings/delete"),
    "update_drawing": ("post", "/api/drawing/"),
    "delete_drawing": ("delete", "/api/drawing/"),
    "list_drawings": ("get", "/api/drawings"),
    "create_subplot": ("post", "/api/subplot"),
    "delete_subplot": ("delete", "/api/subplot/"),
    "list_subplots": ("get", "/api/subplots"),
    "get_kline": ("get", "/api/kline"),
    "get_snapshot": ("get", "/api/snapshot"),
    "watchlist_list": ("get", "/api/watchlist"),
    "watchlist_add": ("post", "/api/watchlist/rows"),
    "watchlist_group_add": ("post", "/api/watchlist/groups"),
    "watchlist_group_rename": ("put", "/api/watchlist/groups/rename"),
    "watchlist_group_remove": ("delete", "/api/watchlist/groups"),
    "watchlist_move": ("put", "/api/watchlist/move"),
    "watchlist_remove": ("delete", "/api/watchlist/rows"),
    "get_quotes": ("get", "/api/quotes"),
    "import_result": ("post", "/api/result"),
    "list_engines": ("get", "/api/engines"),
    "list_strategies": ("get", "/api/strategies"),
    "strategy_meta": ("get", "/api/strategy/meta"),
    "run_backtest": ("post", "/api/backtest"),
    "list_results": ("get", "/api/results"),
    "get_result": ("get", "/api/result/"),
    "rename_result": ("put", "/api/result/"),
    "delete_result": ("delete", "/api/result/"),
    "list_skills": ("get", "/api/skills"),
    "load_skill": ("get", "/api/skills/"),
}


def mcp_tools(base: str, session: requests.Session) -> list:
    """最小 MCP 客户端：initialize → tools/list（SSE 解析 data: 行）"""
    r = session.post(f"{base}/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                           "params": {"protocolVersion": "2025-03-26",
                                                      "capabilities": {},
                                                      "clientInfo": {"name": "e2e", "version": "1"}}},
                     headers={"Accept": "application/json, text/event-stream"})
    sid = r.headers.get("mcp-session-id")
    hdr = {"Accept": "application/json, text/event-stream",
           **({"mcp-session-id": sid} if sid else {})}
    session.post(f"{base}/mcp/", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                 headers=hdr)
    import time as _tm
    payload = None
    for _attempt in range(4):  # SSE 偶发首 chunk 截断 → 重试
        r2 = session.post(f"{base}/mcp/", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                          headers={"Accept": "application/json, text/event-stream",
                                   **({"mcp-session-id": sid} if sid else {})})
        r2.encoding = "utf-8"
        for block in r2.text.split("\n\n"):
            datas = [l[5:].strip() for l in block.splitlines() if l.startswith("data:")]
            if not datas:
                continue
            try:
                cand = json.loads("\n".join(datas))
            except Exception:
                continue
            if cand and "result" in cand:
                payload = cand
                break
        if payload:
            break
        _tm.sleep(0.6)
    if payload is None:
        raise RuntimeError(f"mcp tools/list parse fail: status={r2.status_code} "
                           f"body={r2.text[:200]!r} init_status={r.status_code} sid={sid}")
    return [t["name"] for t in payload["result"]["tools"]]


SYMS_TEST_CODE = (
    'NAME="测试符号源"\nDESC="静态符号表(e2e 自给)"\nPARAMS={"symbol":"X1"}\n'
    'CAPS={"backfill": False, "symbols": True, "ticker": False}\nIDENTITY=["symbol"]\n'
    'SYMS=[{"symbol":"AAA/USD","display":"AAA 现货"},{"symbol":"AAC/USD","display":"AAC 现货"}]\n'
    'def main(params):\n    return []\n'
    'def list_symbols(query=""):\n    q=(query or "").upper()\n'
    '    return [x for x in SYMS if not q or q in x["symbol"]]\n'
)


def test(port: int, token: str = None):
    import time as _tm
    base = f"http://localhost:{port}"
    s = requests.Session()
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal passed, failed
        if condition:
            print(f"  ✅ {name}")
            passed += 1
        else:
            print(f"  ❌ {name} {detail}")
            failed += 1

    print(f"\n{'='*60}\nAgentKline E2E Tests v0.4 (port={port})\n{'='*60}\n")

    # === 1. 建板即锁 / 裸板 ===
    print("🔒 板锁模型")
    r = s.post(f"{base}/api/board", json={"id": "lk", "symbol": "AAA/USDT",
                                          "source": "datasource/mock_btc",
                                          "params": {"days": 60}})
    check("建板即锁(web/agent 同端点)", r.status_code == 200
          and r.json().get("source_lock", {}).get("identity", {}).get("symbol") == "AAA/USDT", r.text)
    r = s.post(f"{base}/api/board", json={"id": "nobare"})
    check("无 symbol 建板被拒 LOCK_REQUIRES_SOURCE", r.status_code == 400, r.text)
    r = s.post(f"{base}/api/board/empty", json={"id": "bare"})
    check("裸板仅 agent 端口 /api/board/empty", r.status_code == 200, r.text)

    # === 2. kline_source 声明式 ===
    print("⚙️ kline_source")
    r = s.put(f"{base}/api/board/bare/timeframe/1d/kline_source",
              json={"script": "datasource/mock_btc", "params": {"symbol": "BBB/USDT", "days": 40}})
    check("空板首配即锁", r.status_code == 200 and r.json().get("count") == 40, r.text)
    r = s.put(f"{base}/api/board/bare/timeframe/1d/kline_source",
              json={"script": "datasource/mock_btc", "params": {"symbol": "BBB/USDT", "days": 40}})
    check("幂等 noop", r.json().get("noop") is True, r.text)
    r = s.put(f"{base}/api/board/bare/timeframe/1d/kline_source",
              json={"script": "datasource/mock_btc", "params": {"symbol": "BBB/USDT", "days": 40},
                    "poll_s": 7})
    check("仅 poll_s 变 = poll_only 不碰数据", r.json().get("poll_only") is True, r.text)
    r = s.put(f"{base}/api/board/bare/timeframe/1d/kline_source",
              json={"script": "datasource/mock_btc", "params": {"symbol": "CCC/USDT"}})
    check("撞锁 409 SOURCE_LOCKED", r.status_code == 409, r.text)
    check("suggestion 一键改道要素齐", r.json().get("detail", {}).get("suggestion", {}).get("action")
          == "create_board", r.text)
    r = s.put(f"{base}/api/board/bare/timeframe/1d/kline_source",
              json={"script": "datasource/mock_btc", "params": {"symbol": "BBB/USDT", "days": 55}})
    check("操作参数自由改(重拉)", r.json().get("count") == 55, r.text)

    # === 3. backfill 门控 ===
    print("📜 backfill")
    r = s.post(f"{base}/api/board/bare/timeframe/1d/backfill", json={"limit": 100})
    check("backfill 前插", r.json().get("prepended", 0) == 100, r.text)
    r = s.post(f"{base}/api/board/bare/timeframe/1d/backfill?limit=7")
    check("backfill query limit 通达（v0.4.4 routes 修）", r.json().get("prepended", 0) == 7, r.text)
    # P1 修复轮 2 契约：until/limit 计数窗（日历无关）+ 空窗=200 空集 + 截断契约
    head = s.get(f"{base}/api/kline", params={"board_id": "bare", "timeframe": "1d"}).json()["ohlcv"][0]["timestamp"]
    r = s.get(f"{base}/api/kline", params={"board_id": "bare", "timeframe": "1d", "until": head, "limit": 7})
    check("until 空窗=200 空集（genesis 探测非错误）", r.status_code == 200 and r.json().get("ohlcv") == [], r.text[:120])
    r = s.post(f"{base}/api/board/bare/timeframe/1d/backfill", json={"limit": 20})
    check("backfill 截断契约 prepended==limit", r.json().get("prepended") == 20, r.text)
    r = s.get(f"{base}/api/kline", params={"board_id": "bare", "timeframe": "1d", "until": head, "limit": 7})
    o = r.json().get("ohlcv") or []
    check("until 窗计数+严格<until+升序", r.status_code == 200 and len(o) == 7
          and all(b["timestamp"] < head for b in o)
          and all(o[i]["timestamp"] < o[i + 1]["timestamp"] for i in range(len(o) - 1)), r.text[:120])
    # v0.4.4 建板失败语义：慢源首拉超 cap = 失败+原因，不建空板
    r = s.post(f"{base}/api/scripts", json={"id": "datasource/slowsrc", "code":
               'NAME="慢源"\nCAPS={"backfill": False, "symbols": False, "ticker": False}\nIDENTITY=[]\n'
               'import time\ndef main(params, until=None):\n    time.sleep(15)\n    return []\n'})
    check("save 慢源", r.status_code == 200, r.text)
    r = s.post(f"{base}/api/board", json={"id": "slowb", "symbol": "X", "source": "datasource/slowsrc"})
    check("慢源建板失败+原因", r.status_code == 400 and "SOURCE_FETCH_TIMEOUT" in r.text, r.text[:150])
    r = s.get(f"{base}/api/boards")
    check("慢源板不残留", all(b["id"] != "slowb" for b in r.json()["boards"]), str([b['id'] for b in r.json()['boards']]))

    s.post(f"{base}/api/scripts", json={"id": "datasource/syms_test", "code": SYMS_TEST_CODE})
    r = s.get(f"{base}/api/search", params={"q": "A", "source": "datasource/syms_test"})
    rows = r.json().get("rows", [])
    check("搜索 source 筛选（v0.4.4）", rows and all(x["source"] == "datasource/syms_test" for x in rows),
          str([x["source"] for x in rows][:4]))
    r = s.post(f"{base}/api/scripts", json={"id": "datasource/nobf", "code":
               'NAME="无回溯"\nCAPS={"backfill": False, "symbols": False, "ticker": False}\nIDENTITY=[]\n'
               'def main(params):\n    return []\n'})
    check("save_script 无徽章源", r.status_code == 200, r.text)
    r = s.post(f"{base}/api/board", json={"id": "nobfboard", "symbol": "X",
                                          "source": "datasource/nobf"})
    check("无回溯源建板", r.status_code == 200, r.text)
    r = s.post(f"{base}/api/board/nobfboard/timeframe/1d/backfill", json={"limit": 50})
    check("NO_BACKFILL 门控", r.json().get("error", "").startswith("NO_BACKFILL"), r.text)

    # === 4. 指标实例 ===
    print("📈 指标实例")
    r = s.post(f"{base}/api/indicator",
               json={"script": "indicator/macd", "subplot": "MACD", "board_id": "bare", "timeframe": "1d"})
    check("recipe 自动 inst_id=macd", r.json().get("inst_id") == "macd", r.text)
    r = s.post(f"{base}/api/indicator",
               json={"inst_id": "macd", "script": "indicator/rsi", "board_id": "bare", "timeframe": "1d"})
    check("撞名 INST_EXISTS", r.status_code == 400 and "INST_EXISTS" in r.text, r.text)
    r = s.post(f"{base}/api/indicator",
               json={"values": [1, 2, 3], "scope": "board", "board_id": "bare", "timeframe": "1d"})
    check("blob 传 scope 报 BLOB_SCOPE", "BLOB_SCOPE" in r.text, r.text)
    r = s.post(f"{base}/api/indicator",
               json={"inst_id": "myblob", "lines": [{"name": "L", "type": "line",
                                                     "values": [1.0] * 55}],
                     "board_id": "bare", "timeframe": "1d"})
    check("blob 钉死本周期", r.json().get("scope") == "timeframe", r.text)
    r = s.put(f"{base}/api/indicator/macd",
              json={"params": {"fastLength": 6, "slowLength": 13, "signalLength": 4},
                    "board_id": "bare", "timeframe": "1d"})
    check("update params 重算+自动名", "MACD(6, 13, 4" in r.text, r.text)
    r = s.get(f"{base}/api/indicators?board_id=bare&timeframe=1d&instances=myblob")
    check("get_indicators instances 过滤", list(r.json().get("indicators", {}).keys()) == ["myblob"], r.text)
    r = s.get(f"{base}/api/overview?board_id=bare&timeframe=1d")
    ov = r.json().get("indicators", {})
    check("overview dynamic=recipe/blob 区分", ov.get("macd", {}).get("dynamic") is True
          and ov.get("myblob", {}).get("dynamic") is False, r.text)
    r = s.delete(f"{base}/api/indicator/myblob?board_id=bare&timeframe=1d")
    check("delete inst_id", r.status_code == 200, r.text)

    # === 4b. P2-fix 显隐服务端真源（刷新持久 + 多端一致） ===
    r = s.put(f"{base}/api/indicator/macd", json={"visible": False, "board_id": "bare", "timeframe": "1d"})
    check("update visible=false 200", r.status_code == 200, r.text)
    r = s.get(f"{base}/api/overview?board_id=bare&timeframe=1d")
    check("overview 回 visible=False（服务端真源，刷新持久）",
          r.json().get("indicators", {}).get("macd", {}).get("visible") is False, r.text[:120])
    r = s.put(f"{base}/api/indicator/macd", json={"visible": True, "board_id": "bare", "timeframe": "1d"})
    r = s.get(f"{base}/api/overview?board_id=bare&timeframe=1d")
    check("update visible=true 恢复", r.json().get("indicators", {}).get("macd", {}).get("visible") is True, r.text[:120])

    # === 5. save_script 校验 + many 压测 ===
    print("🧪 save_script")
    r = s.post(f"{base}/api/scripts", json={"id": "macd", "code": "def main(params, ohlcv):\n    return []\n"})
    check("裸文件名 400 硬切", r.status_code == 400 and "SCRIPT_BAD_ID" in r.text, r.text)
    r = s.post(f"{base}/api/scripts", json={"id": "datasource/bad", "code":
               'CAPS={"backfill": True}\ndef main(params):\n    return []\n'})
    check("CAPS_MISMATCH 保存即校验", "CAPS_MISMATCH" in r.text, r.text)
    params10 = ", ".join(f'"p{i}": {i}' for i in range(1, 11))
    code10 = (f'NAME="TenP"\nDESC="10 参数压测"\nPARAMS={{{params10}}}\n'
              'def main(params, ohlcv):\n    n=int(params.get("p1",1))\n'
              '    return [None]*len(ohlcv) if n<2 else [float(i) for i in range(len(ohlcv))]\n')
    r = s.post(f"{base}/api/scripts", json={"id": "indicator/tenp", "code": code10})
    check("10 参数脚本保存(替代 many.py 夹具)", r.status_code == 200, r.text)
    r = s.post(f"{base}/api/indicator",
               json={"script": "indicator/tenp", "params": {"p1": 3}, "board_id": "bare", "timeframe": "1d"})
    check("10 参数指标上图", r.json().get("inst_id") == "tenp", r.text)

    # === 5b. P1 时间戳契约：recipe values 带 times，按 ts 对齐（索引对齐免疫） ===
    print("⏱️ P1 时间戳契约")
    _HUGE = 9999999999999
    _bars = (s.get(f"{base}/api/kline", params={"board_id": "bare", "timeframe": "1d",
                   "start": 1, "end": _HUGE}).json().get("ohlcv") or [])
    _tenp = (s.get(f"{base}/api/indicators", params={"board_id": "bare", "timeframe": "1d",
               "instances": "tenp", "start": 1, "end": _HUGE}).json()
             .get("indicators", {}).get("tenp", {}))
    _t, _v = _tenp.get("times") or [], _tenp.get("values") or []
    check("P1 get_indicators 回带 times", len(_t) > 0, str(_tenp)[:120])
    check("P1 times/values/bars 同长（全覆盖）",
          len(_t) == len(_v) == len(_bars), f"t={len(_t)} v={len(_v)} bars={len(_bars)}")
    check("P1 times[i]==bars[i].ts（时间戳对齐，非索引猜测）",
          all(_t[i] == _bars[i]["timestamp"] for i in range(min(len(_t), len(_bars)))), "")
    check("P1 tenp values[i]==i（计算值与 ts 同序）",
          all(_v[i] == float(i) for i in range(len(_v))), str(_v[:5]))
    if len(_bars) > 21:
        _p = (s.get(f"{base}/api/indicators", params={"board_id": "bare", "timeframe": "1d",
                "instances": "tenp", "start": _bars[10]["timestamp"],
                "end": _bars[20]["timestamp"]}).json().get("indicators", {}).get("tenp", {}))
        check("P1 部分区间 times==对应 bar ts（bisect 时间范围切片）",
              (_p.get("times") or []) == [_bars[i]["timestamp"] for i in range(10, 21)],
              str((_p.get("times") or [])[:3]))
        check("P1 部分区间 values==[10..20]",
              (_p.get("values") or []) == [float(i) for i in range(10, 21)], str((_p.get("values") or [])[:3]))
    _r = s.post(f"{base}/api/board/bare/timeframe/1d/backfill", json={"limit": 30})
    _prep = _r.json().get("prepended", 0)
    _bars3 = (s.get(f"{base}/api/kline", params={"board_id": "bare", "timeframe": "1d",
                 "start": 1, "end": _HUGE}).json().get("ohlcv") or [])
    _t3 = (s.get(f"{base}/api/indicators", params={"board_id": "bare", "timeframe": "1d",
             "instances": "tenp", "start": 1, "end": _HUGE}).json()
           .get("indicators", {}).get("tenp", {}).get("times") or [])
    _v3 = (s.get(f"{base}/api/indicators", params={"board_id": "bare", "timeframe": "1d",
             "instances": "tenp", "start": 1, "end": _HUGE}).json()
           .get("indicators", {}).get("tenp", {}).get("values") or [])
    check("P1 backfill prepended>0", _prep > 0, _r.text[:120])
    check("P1 prepend 后 times/values/bars 同长（重算覆盖扩展全集）",
          len(_t3) == len(_v3) == len(_bars3), f"t={len(_t3)} v={len(_v3)} bars={len(_bars3)}")
    check("P1 prepend 后 times[i]==bars[i].ts 仍对齐（索引对齐免疫核心）",
          all(_t3[i] == _bars3[i]["timestamp"] for i in range(min(len(_t3), len(_bars3)))), "")
    check("P1 prepend 后 tenp values[i]==i（重算全范围）",
          all(_v3[i] == float(i) for i in range(len(_v3))), str(_v3[:5]))

    # === 6. 搜索 ===
    print("🔍 搜索")
    s.post(f"{base}/api/board", json={"id": "symboard", "symbol": "AAA/USD",
                                      "source": "datasource/syms_test"})
    r = s.get(f"{base}/api/search?q=AA")
    rows = r.json().get("rows", [])
    check("搜索行=二元组+●徽标has_board", any(x["symbol"] == "AAA/USD"
          and x["source"] == "datasource/syms_test" and x["has_board"] for x in rows), r.text)
    check("无板行 has_board=false", any(x["symbol"] == "AAC/USD" and not x["has_board"] for x in rows), r.text)

    # === 7. 加周期自动注入 ===
    print("⏱️ 周期")
    r = s.post(f"{base}/api/scripts", json={"id": "datasource/ivsrc", "code":
               'NAME="IV"\nCAPS={"backfill": False, "symbols": False, "ticker": False}\nIDENTITY=["symbol"]\n'
               'INTERVALS=["5m","1h","1d"]\ndef main(params):\n    return []\n'})
    check("save INTERVALS 字面源", r.status_code == 200, r.text)
    r = s.post(f"{base}/api/board", json={"id": "ivb", "symbol": "IV/X", "source": "datasource/ivsrc"})
    check("实时源建板默认五周期∩支持", r.json().get("intervals") == ["1h", "1d"], r.text)
    r = s.get(f"{base}/api/board/ivb/interval_options")
    d = r.json()
    check("interval_options online+addable", d.get("online") is True and d.get("addable") == ["5m"], r.text)
    r = s.post(f"{base}/api/board/ivb/timeframe", json={"interval": "5m"})
    check("加周期短→长排序", r.json().get("intervals") == ["5m", "1h", "1d"], r.text)
    r = s.get(f"{base}/api/overview?board_id=ivb&timeframe=5m")
    check("新槽自动注入 interval", r.json().get("kline_source", {}).get("params", {}).get("interval") == "5m", r.text)
    r = s.post(f"{base}/api/board/ivb/timeframe", json={"interval": "4h"})
    check("不支持周期被拒 INTERVAL_UNSUPPORTED", "INTERVAL_UNSUPPORTED" in r.text, r.text)
    r = s.get(f"{base}/api/board/bare/interval_options")
    check("空板首配锁不自动扩槽(AI 尊重自建槽) addable=[1w]", r.json().get("addable") == ["1w"], r.text)

    # === 8. 标记/划线/副图（回归） ===
    print("📍 回归")
    kl = s.get(f"{base}/api/kline?board_id=bare&timeframe=1d&start=1&end=9999999999999").json()
    bars = kl.get("ohlcv") or kl.get("bars") or []
    ts0 = bars[10]["timestamp"] if len(bars) > 10 else 0
    r = s.post(f"{base}/api/markers",
               json={"board_id": "bare", "timeframe": "1d",
                     "markers": [{"time": ts0, "position": "aboveBar", "color": "#f00",
                                  "shape": "circle", "text": "t"},
                                 {"time": 1, "position": "aboveBar", "color": "#f00",
                                  "shape": "circle", "text": "bad"}]})
    check("markers 越界丢弃+dropped 回报", len(r.json().get("dropped", [])) == 1
          and r.json().get("count") == 1, r.text)
    # v0.5.2 画线 MCP 面：清单 → 画（绝对/语义锚点）→ 改 → 批量 → 校验
    r = s.get(f"{base}/api/drawing-tools")
    groups = (r.json() or {}).get("groups") or []
    check("画线工具目录 7 组/79 种", r.status_code == 200 and len(groups) == 7
          and sum(g["count"] for g in groups) == 79, r.text[:160])
    r = s.get(f"{base}/api/drawing-tools", params={"category": "fibonacci", "detail": "true"})
    fj = r.json() or {}
    check("按组列工具(含锚点 schema)", fj.get("count") == 23
          and (fj.get("tools") or [{}])[0].get("anchors", {}).get("slots"), r.text[:200])
    r = s.post(f"{base}/api/drawing", json={"board_id": "bare", "type": "trendline",
               "anchors": [{"time": ts0, "price": 1.0}, {"time": ts0 + 86400000, "price": 2.0}],
               "style": {"lineColor": "#42a5f5", "lineWidth": 2, "lineStyle": "solid"}})
    ok = r.status_code == 200 and (r.json().get("drawing") or {}).get("anchors")
    check("draw_drawing 绝对锚点", bool(ok), r.text)
    did = (r.json().get("drawing") or {}).get("id")
    if did:
        r2 = s.post(f"{base}/api/drawing/{did}", json={"board_id": "bare",
                    "patch": {"style": {"lineColor": "#ffee58", "lineWidth": 3, "lineStyle": "dashed"}}})
        check("嵌套 patch 浅合并", (r2.json().get("drawing") or {}).get("style", {}).get("lineColor") == "#ffee58", r2.text)
        s.delete(f"{base}/api/drawing/{did}?board_id=bare")
    r = s.post(f"{base}/api/drawing", json={"board_id": "bare", "type": "hline",
               "anchors": [{"bars_ago": 5, "price": "high"}]})
    h = (r.json().get("drawing") or {})
    check("语义锚点 bars_ago+price 角色", r.status_code == 200 and len(h.get("anchors") or []) == 1
          and h["anchors"][0]["price"] > 0, r.text)
    if h.get("id"):
        s.delete(f"{base}/api/drawing/{h['id']}?board_id=bare")
    r = s.post(f"{base}/api/drawing", json={"board_id": "bare", "type": "hline", "timeframe": "1h",
               "anchors": [{"price": 1.25}]})
    d2 = (r.json().get("drawing") or {})
    check("timeframe 落 showOn 周期带(60)", d2.get("showOn") == ["60"], r.text)
    if d2.get("id"):
        ids1h = [x["id"] for x in s.get(f"{base}/api/drawings?board_id=bare&timeframe=1h").json().get("drawings", [])]
        ids1d = [x["id"] for x in s.get(f"{base}/api/drawings?board_id=bare&timeframe=1d").json().get("drawings", [])]
        check("list_drawings 按 1h 过滤可见", d2["id"] in ids1h, str(ids1h))
        check("list_drawings 按 1d 过滤不可见", d2["id"] not in ids1d, str(ids1d))
        s.delete(f"{base}/api/drawing/{d2['id']}?board_id=bare")
    r = s.post(f"{base}/api/drawings", json={"board_id": "bare", "items": [
        {"type": "hline", "anchors": [{"price": 1.1}]},
        {"type": "trendline", "anchors": [{"bars_ago": 10, "price": "low"}, {"bars_ago": 2, "price": "high"}]}]})
    bt = r.json() or {}
    check("draw_many 批量(2 条)", r.status_code == 200 and bt.get("count") == 2, r.text[:160])
    ids = [d["id"] for d in (bt.get("drawings") or [])]
    rd = s.post(f"{base}/api/drawings/delete", json={"board_id": "bare", "ids": ids + ["nope"]})
    check("delete_drawings 批量删除+missing 回报", rd.status_code == 200
          and len(rd.json().get("deleted") or []) == 2 and rd.json().get("missing") == ["nope"], rd.text[:160])
    r = s.post(f"{base}/api/drawing", json={"board_id": "bare", "type": "hline", "anchors": [{"price": 1.2}]})
    st = (r.json().get("drawing") or {}).get("style")
    check("缺省 style 落库为 {}（Vela fromJSON 必需）", r.status_code == 200 and st == {}, r.text[:160])
    if (r.json().get("drawing") or {}).get("id"):
        s.delete(f"{base}/api/drawing/{(r.json().get('drawing') or {}).get('id')}?board_id=bare")
    r = s.post(f"{base}/api/drawing", json={"board_id": "bare", "type": "nope", "anchors": [{"price": 1}]})
    check("未知类型 400 UNKNOWN_DRAWING_TYPE", r.status_code == 400 and "UNKNOWN_DRAWING_TYPE" in r.text, r.text)
    r = s.post(f"{base}/api/drawing", json={"board_id": "bare", "type": "trendline", "anchors": [{"price": 1}]})
    check("锚点数量校验 400 BAD_ANCHORS", r.status_code == 400 and "BAD_ANCHORS" in r.text, r.text)
    r = s.post(f"{base}/api/drawing", json={"board_id": "bare", "type": "hline", "pane_id": "ak-sub::RSI",
               "anchors": [{"price": 1}]})
    check("副图 pane 暂拒 400 PANE_UNSUPPORTED", r.status_code == 400 and "PANE_UNSUPPORTED" in r.text, r.text)
    r = s.post(f"{base}/api/subplot", json={"name": "p1", "height": 120, "board_id": "bare", "timeframe": "1d"})
    check("subplot 创建", r.status_code == 200, r.text)
    r = s.delete(f"{base}/api/subplot/p1?board_id=bare&timeframe=1d")
    check("subplot 删除", r.status_code == 200, r.text)

    # === 9. 退役端点 404 ===
    print("🪦 退役")
    for method, path, body in [("post", "/api/ohlcv", {"ohlcv": []}),
                               ("post", "/api/load-csv", {"path": "/x"}),
                               ("delete", "/api/board/bare/timeframe/1d/datasource", None),
                               ("post", "/api/board/bare/timeframe/1d/history", {})]:
        r = getattr(s, method)(f"{base}{path}", json=body) if body is not None else getattr(s, method)(f"{base}{path}")
        check(f"{method.upper()} {path} = 404/405", r.status_code in (404, 405), str(r.status_code))

    # === 10. 护栏 ===
    print("🛡 护栏")
    big = ('NAME="六万"\nCAPS={"backfill": False, "symbols": False, "ticker": False}\nIDENTITY=["symbol"]\n'
           'def main(params):\n    return [{"timestamp": 1600000000000+i*60000, "open": 1.0, "high": 1.0,'
           ' "low": 1.0, "close": 1.0, "volume": 1.0} for i in range(60000)]\n')
    s.post(f"{base}/api/scripts", json={"id": "datasource/big", "code": big})
    r = s.post(f"{base}/api/board", json={"id": "bigb", "symbol": "BIG", "source": "datasource/big"})
    check("60000 根截断到 50000", r.status_code == 200, r.text)
    r = s.get(f"{base}/api/overview?board_id=bigb&timeframe=1d")
    check("bars=50000", r.json().get("bars") == 50000, r.text)

    # === 11. MCP ↔ REST 两表面对齐 ===
    print("🔗 两表面对齐")
    try:
        tools = mcp_tools(base, s)
        check("MCP 工具数=55", len(tools) == 55, f"got {len(tools)}")
        missing = [t for t in tools if t not in TOOL_REST_MAP and t not in MCP_ONLY]
        check("无未映射工具", not missing, str(missing))
        spec = s.get(f"{base}/openapi.json").json()
        paths = {p: list(m.keys()) for p, m in spec["paths"].items()}
        bad = []
        for t in tools:
            if t in MCP_ONLY:
                continue
            method, sub = TOOL_REST_MAP[t]
            if not any(sub in p and method in ms for p, ms in paths.items()):
                bad.append(t)
        check("REST 路由全覆盖 MCP（take_snapshot 除外）", not bad, str(bad))
    except Exception as e:
        check("MCP 对齐断言可执行", False, str(e))

    # === 11.5 雷达（v0.4.1） ===
    print("📡 雷达")
    r = s.post(f"{base}/api/watchlist/rows", json={"source": "datasource/mock_btc", "symbol": "RAD/USDT"})
    check("加盯 ok", r.status_code == 200 and r.json().get("status") == "ok", r.text)
    r = s.post(f"{base}/api/watchlist/rows", json={"source": "datasource/csv", "symbol": "X"})
    check("无 ticker 源 TICKER_UNSUPPORTED", r.status_code == 400 and "TICKER_UNSUPPORTED" in r.text, r.text)
    r = s.post(f"{base}/api/watchlist/rows", json={"source": "datasource/mock_btc", "symbol": "RAD/USDT"})
    check("加盯幂等 noop", r.json().get("noop") is True, r.text)
    import time as _t
    _t.sleep(6.5)  # 等一轮 quotes poll（默认 5s）
    r = s.get(f"{base}/api/quotes")
    q = [x for x in r.json().get("quotes", []) if x["symbol"] == "RAD/USDT"]
    check("quotes 心跳有价", bool(q) and q[0]["price"] is not None, r.text[:200])
    check("无板行=watch 态", bool(q) and q[0]["state"] == "watch", r.text[:200])
    r = s.post(f"{base}/api/board", json={"id": "radb", "symbol": "RAD/USDT",
                                          "source": "datasource/mock_btc", "params": {"symbol": "RAD/USDT"}})
    check("雷达行建板即锁", r.status_code == 200, r.text)
    _t.sleep(6.5)
    r = s.get(f"{base}/api/quotes")
    q = [x for x in r.json().get("quotes", []) if x["symbol"] == "RAD/USDT"]
    check("非当前板=hidden 态", bool(q) and q[0]["state"] == "hidden", r.text[:200])
    s.get(f"{base}/api/board/radb")
    _t.sleep(6.5)
    r = s.get(f"{base}/api/quotes")
    q = [x for x in r.json().get("quotes", []) if x["symbol"] == "RAD/USDT"]
    check("当前板=visible 态", bool(q) and q[0]["state"] == "visible", r.text[:200])
    r = s.delete(f"{base}/api/watchlist/rows?source=datasource/mock_btc&symbol=RAD/USDT")
    check("移盯 ok", r.status_code == 200, r.text)
    r = s.delete(f"{base}/api/watchlist/rows?source=datasource/mock_btc&symbol=RAD/USDT")
    check("移盯不存在 404", r.status_code == 404, r.text)

    # === 11.65 内置指标集 + toggle（v0.4.3 A/B） ===
    print("📈 内置指标")
    r = s.post(f"{base}/api/board", json={"id": "indb", "symbol": "IND/USDT",
                                          "source": "datasource/mock_btc", "params": {"symbol": "IND/USDT"}})
    check("指标板建锁", r.status_code == 200, r.text)
    BUILTINS = ["indicator/sma", "indicator/ema", "indicator/bollinger_bands",
                "indicator/supertrend", "indicator/macd", "indicator/kdj",
                "indicator/rsi", "indicator/on_balance_volume"]
    inst_ids = {}
    for ref in BUILTINS:
        r = s.post(f"{base}/api/indicator", json={"board_id": "indb", "timeframe": "1d", "script": ref})
        ok = r.status_code == 200 and not (r.json() or {}).get("error")
        check(f"加 {ref}", ok, r.text[:120])
        if ok:
            inst_ids[ref] = (r.json() or {}).get("inst_id")
    r = s.get(f"{base}/api/indicators?board_id=indb&timeframe=1d")
    inds = r.json().get("indicators") or {}  # {inst_id: inst} dict 面
    sma_inst = next((i for i in inds.values() if (i.get("script") or "").endswith("/sma")), None)
    check("sma 单线（Vela 语义）", bool(sma_inst)
          and [l["name"] for l in (sma_inst.get("lines") or [])] == ["SMA"],
          str(sma_inst and [l["name"] for l in sma_inst.get("lines") or []]))
    check("sma 默认参数 length/source", bool(sma_inst)
          and (sma_inst.get("params") or {}).get("length") == 20
          and (sma_inst.get("params") or {}).get("source") == "Close",
          str(sma_inst and sma_inst.get("params")))
    ema_inst = next((i for i in inds.values() if (i.get("script") or "").endswith("/ema")), None)
    check("ema 单线", bool(ema_inst)
          and [l["name"] for l in (ema_inst.get("lines") or [])] == ["EMA"],
          str(ema_inst and [l["name"] for l in ema_inst.get("lines") or []]))
    check("8 枚全在", len(inds) == 8, f"got {len(inds)}")
    st_inst = next((i for i in inds.values() if (i.get("script") or "").endswith("/supertrend")), None)
    check("supertrend 双线 Uptrend/Downtrend", bool(st_inst)
          and [l["name"] for l in (st_inst.get("lines") or [])] == ["Uptrend", "Downtrend"],
          str(st_inst and [l["name"] for l in st_inst.get("lines") or []]))
    macd_inst = next((i for i in inds.values() if (i.get("script") or "").endswith("/macd")), None)
    check("macd 自动归属副图", bool(macd_inst) and macd_inst.get("subplot") == "macd",
          str(macd_inst and macd_inst.get("subplot")))
    r = s.get(f"{base}/api/subplots?board_id=indb&timeframe=1d")
    subnames = [x.get("name") if isinstance(x, dict) else x for x in (r.json().get("subplots") or [])]
    check("副图列表含 macd", "macd" in subnames, str(subnames))

    # 指标目录（v0.5.3：74 Vela 经典 + KDJ 扩展）
    r = s.get(f"{base}/api/indicator-catalog")
    cat = r.json() if r.status_code == 200 else {}
    cinds = cat.get("indicators") or []
    _builtin = [x for x in cinds if x.get("source") == "builtin"]
    _groups = {g.get("id") for g in (cat.get("groups") or [])}
    check("指标目录 200/内置 75 项", r.status_code == 200 and len(_builtin) == 75,
          f"{r.status_code} builtin={len(_builtin)} total={len(cinds)}")
    check("指标目录 7 内置分类", {"average", "band", "oscillator", "trend",
          "volatility", "volume", "overlay"} <= _groups, str(_groups))
    check("目录脚本 id 唯一", len({x["script"] for x in cinds}) == len(cinds), "")
    check("目录参数 schema 无 color", all(i.get("type") != "color"
          for x in cinds for i in x.get("inputs") or []), "")
    check("目录含 Vela 74 + KDJ", sum(1 for x in _builtin if x["type"] != "kdj") == 74
          and any(x["type"] == "kdj" for x in _builtin), "")
    check("目录 overlay/pane 归属齐全", all(isinstance(x.get("overlay"), bool) for x in cinds), "")
    check("目录含 custom 分类", any(g.get("id") == "custom" for g in cat.get("groups") or []), "")
    check("目录 source 标注", all(x.get("source") in ("builtin", "custom") for x in cinds), "")

    # 新研究实测：stochastic（副图多线）
    r = s.post(f"{base}/api/indicator", json={"board_id": "indb", "timeframe": "1d",
                                              "script": "indicator/stochastic"})
    sid = (r.json() or {}).get("inst_id")
    check("加 stochastic", r.status_code == 200 and bool(sid), r.text[:120])
    r = s.get(f"{base}/api/indicators?board_id=indb&timeframe=1d&instances={sid}")
    st = (r.json().get("indicators") or {}).get(sid) or {}
    check("stochastic 两线 %K/%D", [l["name"] for l in st.get("lines") or []] == ["%K", "%D"],
          str([l["name"] for l in st.get("lines") or []]))
    check("stochastic 默认参数 kLength=14", (st.get("params") or {}).get("kLength") == 14,
          str(st.get("params")))
    if sid:
        s.delete(f"{base}/api/indicator/{sid}?board_id=indb&timeframe=1d")

    # zigzag（polylines）/ williams_fractal（markers）传输
    r = s.post(f"{base}/api/indicator", json={"board_id": "indb", "timeframe": "1d",
                                              "script": "indicator/zigzag"})
    zid = (r.json() or {}).get("inst_id")
    r = s.get(f"{base}/api/indicators?board_id=indb&timeframe=1d&instances={zid}")
    z = (r.json().get("indicators") or {}).get(zid) or {}
    check("zigzag 输出 polylines", len(z.get("polylines") or []) > 0, str(z.keys()))
    if zid:
        s.delete(f"{base}/api/indicator/{zid}?board_id=indb&timeframe=1d")
    r = s.post(f"{base}/api/indicator", json={"board_id": "indb", "timeframe": "1d",
                                              "script": "indicator/williams_fractal"})
    fid = (r.json() or {}).get("inst_id")
    r = s.get(f"{base}/api/indicators?board_id=indb&timeframe=1d&instances={fid}")
    f = (r.json().get("indicators") or {}).get(fid) or {}
    check("fractal 输出 markers", len(f.get("markers") or []) > 0, str(f.keys()))
    if fid:
        s.delete(f"{base}/api/indicator/{fid}?board_id=indb&timeframe=1d")

    # toggle 对：删 sma 再列表无
    if sma_inst:
        r = s.delete(f"{base}/api/indicator/{sma_inst['inst_id']}?board_id=indb&timeframe=1d")
        check("toggle 删 sma", r.status_code == 200, r.text[:100])
        r = s.get(f"{base}/api/indicators?board_id=indb&timeframe=1d")
        check("删后 7 枚", len(r.json().get("indicators") or {}) == 7, "")
    # macd 删后副图回收
    if macd_inst:
        r = s.delete(f"{base}/api/indicator/{macd_inst['inst_id']}?board_id=indb&timeframe=1d")
        check("toggle 删 macd", r.status_code == 200, r.text[:100])
        r = s.get(f"{base}/api/subplots?board_id=indb&timeframe=1d")
        subnames = [x.get("name") if isinstance(x, dict) else x for x in (r.json().get("subplots") or [])]
        check("macd 副图回收", "macd" not in subnames, str(subnames))
        inst_ids.pop("indicator/macd", None)
    for ref, iid in inst_ids.items():
        if iid and not (ref.endswith("/sma")):
            s.delete(f"{base}/api/indicator/{iid}?board_id=indb&timeframe=1d")
    s.delete(f"{base}/api/board/indb")

    # === 11.7 雷达分组（v0.4.2 A） ===
    print("🗂 雷达分组")
    _sfx = str(int(_t.time()))[-4:]  # 组名带运行后缀：跨运行零残留冲突
    r = s.post(f"{base}/api/watchlist/groups", json={"name": f"加密观察{_sfx}"})
    check("建组", r.status_code == 200 and r.json().get("group_id"), r.text[:150])
    gid = r.json()["group_id"]
    r = s.post(f"{base}/api/watchlist/groups", json={"name": f"加密观察{_sfx}"})
    check("重名 GROUP_EXISTS", r.status_code == 400 and "GROUP_EXISTS" in r.text, r.text[:150])
    r = s.post(f"{base}/api/watchlist/rows", json={"source": "datasource/mock_btc",
                                                   "symbol": "G1/USDT", "group_id": gid})
    check("加行带 group_id", r.status_code == 200 and r.json().get("group_id") == gid, r.text[:150])
    r = s.get(f"{base}/api/watchlist")
    grps = {g["id"]: [x["symbol"] for x in g["rows"]] for g in r.json()["groups"]}
    check("行落指定组", grps.get(gid) == ["G1/USDT"], str(grps))
    r = s.put(f"{base}/api/watchlist/groups/rename", json={"group_id": gid, "name": f"链上{_sfx}"})
    check("重命名", r.status_code == 200 and r.json().get("name") == f"链上{_sfx}", r.text[:150])
    r = s.delete(f"{base}/api/watchlist/groups?group_id=default")
    check("默认组保护 GROUP_PROTECTED", r.status_code == 400 and "GROUP_PROTECTED" in r.text, r.text[:150])
    r = s.put(f"{base}/api/watchlist/move", json={"source": "datasource/mock_btc",
                                                  "symbol": "G1/USDT", "group_id": "default", "index": 0})
    check("移组到默认", r.status_code == 200, r.text[:150])
    r = s.get(f"{base}/api/watchlist")
    d0 = [x["symbol"] for x in r.json()["groups"][0]["rows"]]
    check("index=0 置顶", d0[0] == "G1/USDT", str(d0))
    r = s.post(f"{base}/api/watchlist/groups", json={"name": f"临时{_sfx}"})
    gid2 = r.json()["group_id"]
    s.put(f"{base}/api/watchlist/move", json={"source": "datasource/mock_btc",
                                              "symbol": "G1/USDT", "group_id": gid2})
    r = s.delete(f"{base}/api/watchlist/groups?group_id={gid2}")
    check("删组 ok", r.status_code == 200 and r.json().get("deleted_rows") == 1, r.text[:150])
    r = s.get(f"{base}/api/watchlist")
    gids = [g["id"] for g in r.json()["groups"]]
    syms = [x["symbol"] for g in r.json()["groups"] for x in g["rows"]]
    check("删组级联删行（v0.4.3 裁决变更）", gid2 not in gids and "G1/USDT" not in syms, f"{gids} {syms}")
    s.delete(f"{base}/api/watchlist/rows?source=datasource/mock_btc&symbol=G1/USDT")
    s.delete(f"{base}/api/watchlist/groups?group_id={gid}")  # 节尾清组：e2e 自净化

    # === 11.6 性能（v0.4.1 四优化） ===
    print("⚡ 性能")
    r = s.post(f"{base}/api/board", json={"id": "pf1", "symbol": "PF/USDT",
                                          "source": "datasource/mock_btc", "params": {"symbol": "PF/USDT"},
                                          "poll_s": 5})
    check("性能板建锁", r.status_code == 200, r.text)
    s.post(f"{base}/api/view", json={"board_id": "pf1", "timeframe": "1d"})
    r = s.get(f"{base}/api/board/pf1/timeframe/1d/kline_source")
    check("可见槽 eff=poll_s(5)", (r.json().get("kline_source") or {}).get("eff_poll_s") == 5, r.text[:150])
    r = s.post(f"{base}/api/scripts", json={"id": "datasource/pfsrc", "code":
           'NAME="性能源"\nDESC="日内+日两档(e2e)"\nPARAMS={"symbol":"X"}\n'
           'CAPS={"backfill": False, "symbols": False, "ticker": True}\nIDENTITY=["symbol"]\n'
           'INTERVALS=["15m","1d"]\nimport time as _t\n'
           'def main(params, until=None):\n    return []\n'
           'def ticker(params):\n    return {"price": 1.0, "ts": int(_t.time()*1000)}\n'
           'def tickers(pl):\n    return [ticker(p) for p in pl]\n'})
    check("性能源保存", r.status_code == 200, r.text)
    r = s.post(f"{base}/api/board", json={"id": "pf3", "symbol": "P3/USDT",
                                          "source": "datasource/pfsrc", "params": {"symbol": "P3/USDT"},
                                          "poll_s": 5})
    check("性能源板建锁(双槽)", r.status_code == 200, r.text)
    s.post(f"{base}/api/view", json={"board_id": "pf3", "timeframe": "1d"})
    r = s.get(f"{base}/api/board/pf3/timeframe/15m/kline_source")
    check("非可见日内槽 eff=60 降频", (r.json().get("kline_source") or {}).get("eff_poll_s") == 60, r.text[:150])
    # bug5：空 view 上报=清空（tab 隐藏语义）→ 可见槽也降频；再报回→命中
    s.post(f"{base}/api/view", json={})
    r = s.get(f"{base}/api/board/pf3/timeframe/1d/kline_source")
    check("空 view→当前槽免降频(bug11)", (r.json().get("kline_source") or {}).get("eff_poll_s") == 5, r.text[:150])
    eff = None
    for _ in range(10):   # 后台槽配置就位等待
        r = s.get(f"{base}/api/board/pf3/timeframe/15m/kline_source")
        eff = (r.json().get("kline_source") or {}).get("eff_poll_s")
        if eff is not None:
            break
        _tm.sleep(1)
    check("空 view→非当前槽仍降频 60", eff == 60, f"eff={eff}")
    s.post(f"{base}/api/view", json={"board_id": "pf3", "timeframe": "1d"})
    r = s.get(f"{base}/api/board/pf3/timeframe/1d/kline_source")
    check("报回→命中 5s", (r.json().get("kline_source") or {}).get("eff_poll_s") == 5, r.text[:150])
    r = s.get(f"{base}/api/board/pf1/timeframe/1w/kline_source")
    check("非可见周槽 eff=300 降频", (r.json().get("kline_source") or {}).get("eff_poll_s") == 300, r.text[:150])
    s.post(f"{base}/api/watchlist/rows", json={"source": "datasource/mock_btc", "symbol": "B1/USDT"})
    s.post(f"{base}/api/watchlist/rows", json={"source": "datasource/mock_btc", "symbol": "B2/USDT"})
    _t.sleep(6.5)
    r = s.get(f"{base}/api/quotes")
    qs = {q["symbol"]: q for q in r.json().get("quotes", [])}
    check("批量 tick 双行都有价", qs.get("B1/USDT", {}).get("price") is not None
          and qs.get("B2/USDT", {}).get("price") is not None, r.text[:200])
    r = s.post(f"{base}/api/board", json={"id": "pf2", "symbol": "B1/USDT",
                                          "source": "datasource/mock_btc", "params": {"symbol": "B1/USDT"},
                                          "poll_s": 5})
    check("去重板建锁", r.status_code == 200, r.text)
    s.get(f"{base}/api/board/pf2")
    s.post(f"{base}/api/view", json={"board_id": "pf2", "timeframe": "1d"})  # 可见性上报→槽回快频→去重生效
    _t.sleep(6.5)
    kl = s.get(f"{base}/api/kline?board_id=pf2&timeframe=1d").json()
    bars = kl.get("ohlcv") or kl.get("bars") or []
    r = s.get(f"{base}/api/quotes")
    q = [x for x in r.json().get("quotes", []) if x["symbol"] == "B1/USDT"]
    check("可见行 quote=bar close 合成", bool(q) and bool(bars)
          and abs(q[0]["price"] - bars[-1]["close"]) < 1e-6, f"q={q and q[0]['price']} bar={bars and bars[-1]['close']}")
    s.delete(f"{base}/api/watchlist/rows?source=datasource/mock_btc&symbol=B1/USDT")
    s.delete(f"{base}/api/watchlist/rows?source=datasource/mock_btc&symbol=B2/USDT")

    # === 11.9 前端护栏（v0.4.3 C：DAG 判环 + 跨模块未 import 门） ===
    print("🛡 前端护栏")
    import subprocess as _sp
    gr = _sp.run([sys.executable, "scripts/check_fe_guards.py"], capture_output=True, text=True)
    check("护栏：无环+无漏 import", gr.returncode == 0, (gr.stdout + gr.stderr)[:200])

    # === 11.35 内置 A 股源元数据（v0.4.4；不碰真网） ===
    r = s.get(f"{base}/api/scripts")
    lst = r.json().get("scripts", r.json())
    me = next((x for x in lst if x["id"] == "datasource/ashare_free"), None)
    check("builtin 含 ashare_free", me is not None, str([x['id'] for x in lst][:8]))
    if me:
        caps = me.get("caps") or {}
        check("A股源三徽章", caps.get("backfill") and caps.get("symbols") and caps.get("ticker"), str(caps))
        check("A股源 INTERVALS 八档", me.get("intervals") == ["1m", "5m", "15m", "30m", "1h", "1d", "1w", "1mo"],
              str(me.get("intervals")))
    me2 = next((x for x in lst if x["id"] == "datasource/usstock_free"), None)
    check("builtin 含 usstock_free", me2 is not None, str([x['id'] for x in lst][:10]))
    if me2:
        caps2 = me2.get("caps") or {}
        check("美股源三徽章", caps2.get("backfill") and caps2.get("symbols") and caps2.get("ticker"), str(caps2))

    # === 11.36 脚本元数据只读路由（web 端口可读，供设置面板补 PARAMS 默认值） ===
    r = s.get(f"{base}/api/scripts/meta")
    check("scripts/meta 200", r.status_code == 200, r.text[:120])
    ml = r.json().get("scripts", []) if r.status_code == 200 else []
    check("scripts/meta 含内置指标", any(x.get("id") == "indicator/bollinger_bands" for x in ml),
          str([x.get("id") for x in ml][:6]))
    _bbm = next((x for x in ml if x.get("id") == "indicator/bollinger_bands"), None) or {}
    check("scripts/meta 带 PARAMS 默认值", _bbm.get("params") == {"length": 20, "source": "Close", "mult": 2},
          str(_bbm.get("params")))
    check("scripts/meta 精简面（不含能力/数据源元数据）",
          all(not ({"caps", "identity", "intervals"} & set(x.keys())) for x in ml),
          str(sorted(ml[0].keys())) if ml else "empty")

    # === 11.4 skills 四卷（v0.4.4 拆分；0.6.1 增策略卷） ===
    print("📚 skills")
    r = s.get(f"{base}/api/skills")
    names = sorted(x["name"] for x in r.json().get("skills", r.json()))
    check("skills 四卷齐", names == ["ai-walkthrough", "datasource-authoring",
                                    "indicator-authoring", "strategy-authoring"], str(names))
    r = s.get(f"{base}/api/skills/datasource-authoring")
    body = r.json().get("content", r.text)
    check("datasource 卷含契约章+内联模板", "datasource 契约" in body and "INTERVALS" in body
          and "<!-- include" not in body and "CAPS = {" in body and "def main(params" in body,
          body[:80])
    r = s.get(f"{base}/api/skills/indicator-authoring")
    body = r.json().get("content", r.text)
    check("indicator 卷含 SUBPLOT+内联模板", "SUBPLOT" in body and "indicator 契约" in body
          and "<!-- include" not in body and '"lines"' in body, body[:80])
    r = s.get(f"{base}/api/skills/strategy-authoring")
    body = r.json().get("content", r.text)
    check("strategy 卷含契约+内联模板",
          r.status_code == 200 and "main 契约" in body and "<!-- include" not in body
          and 'STRATEGY_MODE = "signal"' in body and "def main(params, ohlcv):" in body,
          body[:120])

    # === 11.5 MCP 提示词黑话门禁（v0.4.4） ===
    print("📜 MCP docstring 黑话门禁")
    # bug10 回归：建板不传 poll_s 也必须有活轮询线程（曾致 set_config 后线程不启=价格永冻）
    r = s.post(f"{base}/api/board", json={"id": "bug10probe", "symbol": "B10/USDT",
                                                "source": "datasource/mock_btc"})
    check("bug10 建板(无 poll_s) 200", r.status_code == 200, r.text)
    # 线程启动铁证 = 服务 log 的 started 行（e2e 自带 WS 上报者，headless 语义在 e2e 内不成立，
    # bug11 免降频断言保留性能段 pf3 对（WS 连接前 view 真空窗））
    import glob as _g
    logf = "/tmp/agentkline.log"
    body = open(logf, errors="ignore").read() if _g.os.path.exists(logf) else ""
    check("bug10 轮询线程启动(started log)", "DataSource started: bug10probe:1d" in body,
          "log 无 started 行")
    s.delete(f"{base}/api/board/bug10probe")


    section_docstring_jargon(check)

    # === 11.8 结果实例（v0.6.0） ===
    print("📈 结果实例")
    r = s.post(f"{base}/api/board", json={"id": "resb", "symbol": "RES/USDT",
                                          "source": "datasource/mock_btc", "params": {"days": 80}})
    check("结果板建板", r.status_code == 200, r.text)
    kl = s.get(f"{base}/api/kline?board_id=resb&timeframe=1d").json().get("ohlcv") or []
    check("结果板有 K 线", len(kl) > 20, str(len(kl)))
    times = [b["timestamp"] for b in kl]
    vals = [10000.0 * (b["close"] / kl[0]["close"]) for b in kl]
    payload = {
        "board_id": "resb", "timeframe": "1d", "display_name": "e2e 结果",
        "equity": {"times": times, "values": vals},
        "trades": [{"entry_time": times[5], "exit_time": times[9], "entry_price": kl[5]["close"],
                    "exit_price": kl[9]["close"], "size": 1.0, "pnl": 10.0, "fee": 0.5,
                    "entry_reason": "e2e", "exit_reason": "e2e"}],
        "strategy": {"id": "strategy/e2e", "mode": "signal", "params": {"x": 1}},
        "run": {"initial_cash": 10000, "bars_per_year": 365},
        "execution_assumptions": {"fill_rule": "next_open"},
    }
    r = s.post(f"{base}/api/result", json={"payload": payload})
    check("导入结果", r.status_code == 200 and r.json().get("result", {}).get("result_id"), r.text[:200])
    rid = r.json()["result"]["result_id"]
    check("结果摘要口径齐", all(k in r.json()["result"].get("stats", {})
                              for k in ("total_return", "max_drawdown", "sharpe", "profit_factor")), r.text[:200])
    r = s.get(f"{base}/api/results?board_id=resb")
    check("结果列表", r.status_code == 200 and any(x["result_id"] == rid for x in r.json().get("results", [])), r.text[:200])
    r = s.get(f"{base}/api/result/{rid}?section=equity&limit=5")
    check("结果净值分页", r.status_code == 200 and r.json().get("returned") == 5
          and r.json().get("truncated") is True, r.text[:200])
    r = s.put(f"{base}/api/result/{rid}", json={"display_name": "e2e 改名"})
    check("结果改名", r.status_code == 200 and r.json().get("display_name") == "e2e 改名", r.text[:200])
    bad = dict(payload, equity={"times": times, "values": [v + 1 for v in vals]},
               run={"initial_cash": 10000})
    r = s.post(f"{base}/api/result", json={"payload": bad})
    check("equity[0]!=初始资金 拒收", r.status_code == 400, r.text[:160])
    r = s.delete(f"{base}/api/result/{rid}")
    check("结果删除", r.status_code == 200, r.text[:200])
    s.delete(f"{base}/api/board/resb")

    # === 11.9 引擎回测（v0.6.1） ===
    print("🧮 引擎回测")
    r = s.get(f"{base}/api/engines")
    engines = (r.json() or {}).get("engines") or []
    check("引擎清单", r.status_code == 200
          and any(e["id"] == "builtin" and e["api"] == 1 and e["caps"].get("signal")
                  for e in engines), r.text[:200])
    r = s.get(f"{base}/api/strategies")
    strategies = (r.json() or {}).get("strategies") or []
    check("策略清单（只读）", r.status_code == 200
          and any(x["id"] == "strategy/ma_cross" for x in strategies), r.text[:200])
    r = s.get(f"{base}/api/strategy/meta", params={"script": "strategy/ma_cross"})
    meta = r.json()
    check("策略声明（AST，不执行）", r.status_code == 200 and meta.get("ok")
          and meta.get("warmup") == 30 and "fast" in (meta.get("params") or {}),
          r.text[:200])
    bad_src = ('STRATEGY_MODE = "event"\nNAME = "e2e_bad"\nWARMUP = 0\nPARAMS = {}\n'
               'def main(p, o):\n    return {}\n')
    r = s.post(f"{base}/api/scripts", json={"id": "strategy/e2e_bad", "code": bad_src})
    check("策略保存即验 MODE_MISMATCH", r.status_code == 400 and "MODE_MISMATCH" in r.text, r.text[:200])

    r = s.post(f"{base}/api/board", json={"id": "btb", "symbol": "BT/USDT",
                                          "source": "datasource/mock_btc",
                                          "params": {"days": 300}})
    check("回测板建板", r.status_code == 200, r.text[:200])
    body = {"board_id": "btb", "timeframe": "1d", "script": "strategy/ma_cross",
            "direction": "long_only", "initial_cash": 10000, "limit": 300}
    r = s.post(f"{base}/api/backtest", json=body)
    j = r.json()
    res = j.get("result") or {}
    rid1 = res.get("result_id")
    check("回测产出结果", r.status_code == 200 and rid1
          and res.get("engine", {}).get("id") == "builtin"
          and res.get("stats", {}).get("trade_count", 0) > 0, r.text[:300])
    check("回测结果带引擎口径", bool(res.get("execution_assumptions", {}).get("fill_rule"))
          and res.get("strategy", {}).get("warmup") == 30, r.text[:300])
    r2 = s.post(f"{base}/api/backtest", json=body)
    check("重跑=新结果（冻结）", r2.json().get("result", {}).get("result_id") not in (None, rid1),
          r2.text[:200])

    # CLI 与 API 同 spec 逐数一致（B3）
    try:
        bars_all = s.get(f"{base}/api/kline?board_id=btb&timeframe=1d").json().get("ohlcv") or []
        run_info = j.get("run") or {}
        warm = int(run_info.get("warmup_bars") or 0)
        to_idx = max(i for i, b in enumerate(bars_all)
                     if b["timestamp"] <= int(run_info["to"]))
        from_idx = next(i for i, b in enumerate(bars_all)
                        if b["timestamp"] == int(run_info["from"]))
        bars = bars_all[max(0, from_idx - warm):to_idx + 1]
        strat_src = open(os.path.join(os.path.dirname(__file__),
                                      "agentkline/resources/scripts/strategy/ma_cross.py"),
                         encoding="utf-8").read()
        spec_obj = {"api": 1, "engine": "builtin", "bars": bars,
                    "strategy": {"source": strat_src},
                    "run": {"initial_cash": 10000, "fee_bps": 5, "slippage_bps": 5,
                            "direction": "long_only", "params": {}, "eval_start": warm},
                    "timeframe": "1d"}
        import subprocess as _sp
        ak = os.path.join(os.path.dirname(__file__), ".venv", "bin", "ak-engine")
        proc = _sp.run([ak, "run", "--stdin"], input=json.dumps(spec_obj),
                       capture_output=True, text=True, timeout=120)
        lines = proc.stdout.splitlines()
        cli = json.loads(lines[1]) if lines and lines[0] == "__AK_RESULT__" else {}
        eq_api = s.get(f"{base}/api/result/{rid1}?section=equity&limit=0").json()
        tr_api = s.get(f"{base}/api/result/{rid1}?section=trades&limit=0").json()
        same_eq = (eq_api.get("values") or []) == (cli.get("equity") or {}).get("values")
        same_trades = len(tr_api.get("items") or []) == len(cli.get("trades") or [])
        check("CLI/API 同 spec 逐数一致", same_eq and same_trades,
              f"eq={same_eq} trades={len(tr_api.get('items') or [])}/"
              f"{len(cli.get('trades') or [])}")
    except Exception as exc:  # noqa: BLE001
        check("CLI/API 同 spec 逐数一致", False, f"{type(exc).__name__}: {exc}")

    # B8 方向：同一份 ±1 目标，both 下必须出现空头
    both_src = ('STRATEGY_MODE = "signal"\nNAME = "e2e_both"\nWARMUP = 2\nPARAMS = {}\n'
                'def main(p, o):\n'
                '    return {"target": [0.0, 0.0] + [1.0 if i % 2 else -1.0 '
                'for i in range(len(o) - 2)]}\n')
    r = s.post(f"{base}/api/backtest", json={"board_id": "btb", "timeframe": "1d",
                                             "source": both_src, "direction": "both",
                                             "initial_cash": 10000})
    ridb = (r.json().get("result") or {}).get("result_id")
    items = []
    if ridb:
        items = s.get(f"{base}/api/result/{ridb}?section=trades&limit=0").json().get("items") or []
    sides = {t["side"] for t in items}
    check("方向 both 出现多空两侧", r.status_code == 200 and sides == {"long", "short"},
          f"{r.text[:120]} sides={sides}")

    # B9 参数校验：越界参数由引擎拒绝，错误码透传
    r = s.post(f"{base}/api/backtest", json={"board_id": "btb", "timeframe": "1d",
                                             "script": "strategy/ma_cross",
                                             "params": {"fast": 1}})
    check("参数越界被拒 PARAMS_INVALID", r.status_code == 400 and "PARAMS_INVALID" in r.text,
          r.text[:160])
    r = s.post(f"{base}/api/backtest", json={"board_id": "btb", "timeframe": "1d",
                                             "script": "strategy/no_such"})
    check("策略不存在 SCRIPT_NOT_FOUND", r.status_code == 400 and "SCRIPT_NOT_FOUND" in r.text,
          r.text[:160])
    s.delete(f"{base}/api/board/btb")

    # === 12. 清理 ===
    print("🧹 清理")
    for bid in ["lk", "bare", "nobfboard", "bigb", "symboard", "ivb", "radb", "pf1", "pf2", "pf3"]:  # slowb 断言不残留，清理段不删
        r = s.delete(f"{base}/api/board/{bid}")
        check(f"delete {bid}", r.status_code == 200, r.text)
    # e2e 自己写的压测脚本不留在仓库（save_script 无删除 API，直接清文件）
    try:
        os.remove(os.path.join(os.environ.get("AGENTKLINE_SCRIPTS_DIR")
                               or os.path.join(os.path.dirname(__file__), "scripts"),
                               "indicator", "tenp.py"))
    except OSError:
        pass

    print(f"\n{'='*60}\nResults: {passed} passed, {failed} failed, {passed+failed} total\n{'='*60}\n")
    return failed == 0


# ── MCP 提示词黑话门禁（v0.4.4）：MCP 面 docstring 禁开发者黑话，防回归 ──
def section_docstring_jargon(check):
    import ast as _ast
    JARGON = ["把手", "窄身", "登记处", "物化", "二元组", "前插", "槽", "锁字段",
              "重声明配方", "identity 快照", "回落默认组", "徽章"]
    tree = _ast.parse(open(os.path.join(os.path.dirname(__file__), "agentkline/api/tools.py")).read())
    bad = []
    for node in tree.body:
        if not isinstance(node, _ast.FunctionDef):
            continue
        mcp_on = True
        for dec in node.decorator_list:
            if isinstance(dec, _ast.Call) and getattr(dec.func, "id", "") == "api_tool":
                for kw in dec.keywords:
                    if kw.arg == "mcp" and getattr(kw.value, "value", True) is False:
                        mcp_on = False
    # ---- v0.4.5 前端 i18n 门禁：组件零中文硬编码（串表唯一源=i18n.js） ----
    import re as _re2
    bad_i18n = []
    src_dir = os.path.join(os.path.dirname(__file__), "frontend", "src")
    for fn in sorted(os.listdir(src_dir)):
        if not fn.endswith(".js") or fn == "i18n.js":
            continue  # locales/ 语言包=串表唯一源，核心 i18n.js 零串
        for i, line in enumerate(open(os.path.join(src_dir, fn), encoding="utf-8"), 1):
            if "lang() === 'zh'" in line or "切换到中文" in line:
                continue  # 语言 toggle 的语言名=合法例外
            for m in _re2.finditer(r"['\"`][^'\"`]*[\u4e00-\u9fa5][^'\"`]*['\"`]", line):
                bad_i18n.append(f"{fn}:{i}:{m.group(0)[:30]}")
    check("前端组件零中文硬编码(i18n 门禁)", not bad_i18n, str(bad_i18n[:5]))

    # ---- MCP 面黑话门禁 ----
    import ast as _ast
    _tree = _ast.parse(open(os.path.join(os.path.dirname(__file__),
                                         "agentkline", "api", "tools.py")).read())
    bad = []
    for node in _ast.walk(_tree):
        if not mcp_on:
            continue
        doc = _ast.get_docstring(node) or ""
        for w in JARGON:
            if w in doc:
                bad.append(f"{node.name}:{w}")
    check("MCP docstring 无黑话", not bad, str(bad))
    # skills 禁版本标记：消费方 agent 只应"读了就能用"，版本-技能匹配是发布方义务
    import glob as _glob, re as _re
    vb = []
    for f in _glob.glob(os.path.join(os.path.dirname(__file__), "skills/*.md")):
        for i, line in enumerate(open(f), 1):
            if _re.search(r"v0\.\d", line):
                vb.append(f"{os.path.basename(f)}:{i}")
    check("skills 无版本标记", not vb, str(vb))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766, help="agent 端口（默认 8766）")
    parser.add_argument("--token", default=os.environ.get("AGENTKLINE_TOKEN"),
                        help="agent 端口 Bearer token（默认取环境变量 AGENTKLINE_TOKEN）")
    args = parser.parse_args()
    success = test(args.port, args.token)
    sys.exit(0 if success else 1)
