#!/usr/bin/env python3
"""v0.5 换底 smoke：headless 开活体页，抓 console + 截图。"""
import sys, os
from playwright.sync_api import sync_playwright

URL = os.environ.get("SMOKE_URL", "http://127.0.0.1:8765/")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smoke.png")

logs = []
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox", "--disable-gpu"])
    pg = br.new_page(viewport={"width": 1600, "height": 1000})
    pg.on("console", lambda m: logs.append(f"[{m.type}] {m.text[:300]}"))
    pg.on("pageerror", lambda e: logs.append(f"[pageerror] {e}"))
    pg.goto(URL, wait_until="load")
    pg.wait_for_timeout(6000)
    pg.screenshot(path=OUT)
    br.close()
print("\n".join(logs[:40]))
print("shot:", OUT)
