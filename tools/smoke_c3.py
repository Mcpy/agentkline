#!/usr/bin/env python3
"""C3 交互 smoke：侧栏 hline 按钮 → 图上点击画线 → 写回存储验证。"""
import os, json, urllib.request
from playwright.sync_api import sync_playwright

TOKEN = os.environ.get("AK_TOKEN", "")
logs = []
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox", "--disable-gpu"])
    pg = br.new_page(viewport={"width": 1600, "height": 1000})
    pg.on("console", lambda m: logs.append(f"[{m.type}] {m.text[:200]}"))
    pg.on("pageerror", lambda e: logs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:8765/", wait_until="load")
    pg.wait_for_timeout(5000)
    # 点侧栏 hline 按钮
    pg.mouse.click(20, 181)
    pg.wait_for_timeout(800)
    # 图上点击放置 hline
    pg.mouse.click(700, 300)
    pg.wait_for_timeout(1500)
    pg.screenshot(path="tools/smoke_c3.png")
    br.close()
print("\n".join([l for l in logs if 'WebGL' not in l][:15]))
# 写回验证：REST list_drawings
req = urllib.request.Request("http://127.0.0.1:8766/api/drawings?board_id=smoke&timeframe=1d",
                             headers={"Authorization": f"Bearer {TOKEN}"})
try:
    d = json.load(urllib.request.urlopen(req))
    print("storage drawings:", json.dumps(d, ensure_ascii=False)[:400])
except Exception as e:
    print("list err:", e)
