#!/usr/bin/env python3
"""
AgentKline - API 参考附录生成器（防漂移三件套③）
从运行中服务生成 REST 路由表 + MCP 工具表，输出 Markdown 到 stdout（可重定向进文档附录）。
用法: python scripts/gen_api_ref.py [--port 8766] [--token T]
"""
import argparse
import json
import os
import requests


def mcp_tool_names(base, session):
    r = session.post(f"{base}/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                           "params": {"protocolVersion": "2025-03-26",
                                                      "capabilities": {},
                                                      "clientInfo": {"name": "gen", "version": "1"}}},
                     headers={"Accept": "application/json, text/event-stream"})
    sid = r.headers.get("mcp-session-id")
    hdr = {"Accept": "application/json, text/event-stream",
           **({"mcp-session-id": sid} if sid else {})}
    session.post(f"{base}/mcp/", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                 headers=hdr)
    names = []
    for _ in range(4):
        r2 = session.post(f"{base}/mcp/", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                          headers=hdr)
        r2.encoding = "utf-8"
        for block in r2.text.split("\n\n"):
            datas = [l[5:].strip() for l in block.splitlines() if l.startswith("data:")]
            if not datas:
                continue
            try:
                p = json.loads("\n".join(datas))
            except Exception:
                continue
            if p and "result" in p:
                return [(t["name"], t.get("description", "").splitlines()[0] if t.get("description") else "")
                        for t in p["result"]["tools"]]
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--token", default=os.environ.get("AGENTKLINE_TOKEN"))
    a = ap.parse_args()
    base = f"http://localhost:{a.port}"
    s = requests.Session()
    if a.token:
        s.headers["Authorization"] = f"Bearer {a.token}"

    spec = s.get(f"{base}/openapi.json").json()
    print("# 附录 A：REST 路由表（自动生成，勿手改）\n")
    print("| 方法 | 路径 | 摘要 |")
    print("|---|---|---|")
    for path, methods in sorted(spec["paths"].items()):
        for m, op in methods.items():
            if m in ("get", "post", "put", "delete", "patch"):
                print(f"| {m.upper()} | `{path}` | {op.get('summary', '')} |")

    print("\n# 附录 B：MCP 工具表（自动生成，勿手改）\n")
    print("| 工具 | 说明首行 |")
    print("|---|---|")
    for name, desc in mcp_tool_names(base, s):
        print(f"| `{name}` | {desc} |")


if __name__ == "__main__":
    main()
