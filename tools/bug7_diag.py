#!/usr/bin/env python3
"""bug7 精测：锁定 3 个月视口 → 左划 backfill → 视口跨度前后对照。"""
import json, os, urllib.request
from playwright.sync_api import sync_playwright

TOKEN = os.environ["AK_TOKEN"]
BASE = "http://127.0.0.1:8766"
B = "b_btc_usdt_usdt_mush7fp0"
TF = "1d"

def api(path, method="GET", body=None):
    req = urllib.request.Request(BASE + path, method=method,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body else None)
    return json.load(urllib.request.urlopen(req))

def cur():
    d = api(f"/api/view?board_id={B}&timeframe={TF}")
    return d.get("from"), d.get("to")

with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox", "--disable-gpu"])
    pg = br.new_page(viewport={"width": 1600, "height": 1000})
    pg.goto("http://127.0.0.1:8765/", wait_until="load")
    pg.wait_for_timeout(6000)
    # 取 bars 范围，锁 3 个月（~92 天）视口于右缘
    kl = api(f"/api/kline?board_id={B}&timeframe={TF}&start=1&end=99999999999999")
    bars = kl.get("ohlcv") or []
    last = bars[-1]["timestamp"]
    frm = last - 92 * 86400
    api(f"/api/view/range?board_id={B}&timeframe={TF}", "POST", {"from_time": frm, "to_time": last + 86400})
    pg.wait_for_timeout(1200)
    f0, t0 = cur()
    print(f"backfill 前视口: {f0} → {t0}  跨度 {(t0-f0)/86400:.1f} 天")
    # 左划触发 backfill
    box = pg.evaluate("() => { const r=document.getElementById('main-chart').getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; }")
    pg.mouse.move(box['x']+box['w']*0.5, box['y']+box['h']*0.5)
    for _ in range(60):
        pg.mouse.wheel(0, 400)
        pg.wait_for_timeout(120)
    pg.wait_for_timeout(3000)
    f1, t1 = cur()
    print(f"backfill 后视口: {f1} → {t1}  跨度 {(t1-f1)/86400:.1f} 天")
    print(">> 视口被压缩?", (t1-f1) < (t0-f0) * 0.5)
    pg.screenshot(path="tools/bug7_diag.png")
    br.close()
