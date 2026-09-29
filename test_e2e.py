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
    "add_drawing": ("post", "/api/drawing"),
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
    # v0.4.4 建板失败语义：慢源首拉超 cap = 失败+原因，不建空板
    r = s.post(f"{base}/api/scripts", json={"id": "datasource/slowsrc", "code":
               'NAME="慢源"\nCAPS={"backfill": False, "symbols": False, "ticker": False}\nIDENTITY=[]\n'
               'import time\ndef main(params, until=None):\n    time.sleep(15)\n    return []\n'})
    check("save 慢源", r.status_code == 200, r.text)
    r = s.post(f"{base}/api/board", json={"id": "slowb", "symbol": "X", "source": "datasource/slowsrc"})
    check("慢源建板失败+原因", r.status_code == 400 and "SOURCE_FETCH_TIMEOUT" in r.text, r.text[:150])
    r = s.get(f"{base}/api/boards")
    check("慢源板不残留", all(b["id"] != "slowb" for b in r.json()["boards"]), str([b['id'] for b in r.json()['boards']]))

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
              json={"params": {"fast": 6, "slow": 13, "signal": 4}, "board_id": "bare", "timeframe": "1d"})
    check("update params 重算+自动名", "MACD(6, 13, 4)" in r.text, r.text)
    r = s.get(f"{base}/api/indicators?board_id=bare&timeframe=1d&instances=myblob")
    check("get_indicators instances 过滤", list(r.json().get("indicators", {}).keys()) == ["myblob"], r.text)
    r = s.get(f"{base}/api/overview?board_id=bare&timeframe=1d")
    ov = r.json().get("indicators", {})
    check("overview dynamic=recipe/blob 区分", ov.get("macd", {}).get("dynamic") is True
          and ov.get("myblob", {}).get("dynamic") is False, r.text)
    r = s.delete(f"{base}/api/indicator/myblob?board_id=bare&timeframe=1d")
    check("delete inst_id", r.status_code == 200, r.text)

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

    # === 6. 搜索 ===
    print("🔍 搜索")
    s.post(f"{base}/api/scripts", json={"id": "datasource/syms_test", "code":
           'NAME="测试符号源"\nDESC="静态符号表(e2e 自给)"\nPARAMS={"symbol":"X1"}\n'
           'CAPS={"backfill": False, "symbols": True, "ticker": False}\nIDENTITY=["symbol"]\n'
           'SYMS=[{"symbol":"AAA/USD","display":"AAA 现货"},{"symbol":"AAC/USD","display":"AAC 现货"}]\n'
           'def main(params):\n    return []\n'
           'def list_symbols(query=""):\n    q=(query or "").upper()\n'
           '    return [x for x in SYMS if not q or q in x["symbol"]]\n'})
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
        check("MCP 工具数=43", len(tools) == 43, f"got {len(tools)}")
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
    BUILTINS = ["indicator/sma", "indicator/ema", "indicator/bb", "indicator/sar",
                "indicator/macd", "indicator/kdj", "indicator/rsi", "indicator/obv"]
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
    check("sma 三线 MA5/10/20", bool(sma_inst) and [l["name"] for l in (sma_inst.get("lines") or [])] == ["MA5", "MA10", "MA20"],
          str(sma_inst and [l["name"] for l in sma_inst.get("lines") or []]))
    ema_inst = next((i for i in inds.values() if (i.get("script") or "").endswith("/ema")), None)
    check("ema 三线 EMA5/10/20", bool(ema_inst) and [l["name"] for l in (ema_inst.get("lines") or [])] == ["EMA5", "EMA10", "EMA20"],
          str(ema_inst and [l["name"] for l in ema_inst.get("lines") or []]))
    check("8 枚全在", len(inds) == 8, f"got {len(inds)}")
    check("sma 实例带默认参数", bool(sma_inst) and (sma_inst.get("params") or {}).get("periods") == [5, 10, 20],
          str(sma_inst and sma_inst.get("params")))
    macd_inst = next((i for i in inds.values() if (i.get("script") or "").endswith("/macd")), None)
    check("macd 自动归属副图", bool(macd_inst) and macd_inst.get("subplot") == "macd",
          str(macd_inst and macd_inst.get("subplot")))
    r = s.get(f"{base}/api/subplots?board_id=indb&timeframe=1d")
    subnames = [x.get("name") if isinstance(x, dict) else x for x in (r.json().get("subplots") or [])]
    check("副图列表含 macd", "macd" in subnames, str(subnames))
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

    # === 11.4 skills 三卷（v0.4.4 拆分） ===
    print("📚 skills")
    r = s.get(f"{base}/api/skills")
    names = sorted(x["name"] for x in r.json().get("skills", r.json()))
    check("skills 三卷齐", names == ["ai-walkthrough", "datasource-authoring", "indicator-authoring"], str(names))
    r = s.get(f"{base}/api/skills/datasource-authoring")
    body = r.json().get("content", r.text)
    check("datasource 卷含契约章", "datasource 契约" in body and "INTERVALS" in body, body[:80])
    r = s.get(f"{base}/api/skills/indicator-authoring")
    body = r.json().get("content", r.text)
    check("indicator 卷含 SUBPLOT", "SUBPLOT" in body and "indicator 契约" in body, body[:80])

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

    # === 12. 清理 ===
    print("🧹 清理")
    for bid in ["lk", "bare", "nobfboard", "bigb", "symboard", "ivb", "radb", "pf1", "pf2", "pf3"]:  # slowb 断言不残留，清理段不删
        r = s.delete(f"{base}/api/board/{bid}")
        check(f"delete {bid}", r.status_code == 200, r.text)

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
