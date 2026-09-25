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
    r = s.post(f"{base}/api/indicator?board_id=bare&timeframe=1d",
               json={"script": "indicator/macd", "subplot": "MACD"})
    check("recipe 自动 inst_id=macd", r.json().get("inst_id") == "macd", r.text)
    r = s.post(f"{base}/api/indicator?board_id=bare&timeframe=1d",
               json={"inst_id": "macd", "script": "indicator/rsi"})
    check("撞名 INST_EXISTS", r.status_code == 400 and "INST_EXISTS" in r.text, r.text)
    r = s.post(f"{base}/api/indicator?board_id=bare&timeframe=1d",
               json={"values": [1, 2, 3], "scope": "board"})
    check("blob 传 scope 报 BLOB_SCOPE", "BLOB_SCOPE" in r.text, r.text)
    r = s.post(f"{base}/api/indicator?board_id=bare&timeframe=1d",
               json={"inst_id": "myblob", "lines": [{"name": "L", "type": "line",
                                                     "values": [1.0] * 55}]})
    check("blob 钉死本周期", r.json().get("scope") == "timeframe", r.text)
    r = s.put(f"{base}/api/indicator/macd?board_id=bare&timeframe=1d",
              json={"params": {"fast": 6, "slow": 13, "signal": 4}})
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
    r = s.post(f"{base}/api/indicator?board_id=bare&timeframe=1d",
               json={"script": "indicator/tenp", "params": {"p1": 3}})
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
    r = s.post(f"{base}/api/markers?board_id=bare&timeframe=1d",
               json={"markers": [{"time": ts0, "position": "aboveBar", "color": "#f00",
                                  "shape": "circle", "text": "t"},
                                 {"time": 1, "position": "aboveBar", "color": "#f00",
                                  "shape": "circle", "text": "bad"}]})
    check("markers 越界丢弃+dropped 回报", len(r.json().get("dropped", [])) == 1
          and r.json().get("count") == 1, r.text)
    r = s.post(f"{base}/api/subplot?board_id=bare&timeframe=1d", json={"name": "p1", "height": 120})
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
        check("MCP 工具数=35", len(tools) == 35, f"got {len(tools)}")
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

    # === 12. 清理 ===
    print("🧹 清理")
    for bid in ["lk", "bare", "nobfboard", "bigb", "symboard", "ivb"]:
        r = s.delete(f"{base}/api/board/{bid}")
        check(f"delete {bid}", r.status_code == 200, r.text)

    print(f"\n{'='*60}\nResults: {passed} passed, {failed} failed, {passed+failed} total\n{'='*60}\n")
    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766, help="agent 端口（默认 8766）")
    parser.add_argument("--token", default=os.environ.get("AGENTKLINE_TOKEN"),
                        help="agent 端口 Bearer token（默认取环境变量 AGENTKLINE_TOKEN）")
    args = parser.parse_args()
    success = test(args.port, args.token)
    sys.exit(0 if success else 1)
