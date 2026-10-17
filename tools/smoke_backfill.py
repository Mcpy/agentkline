#!/usr/bin/env python3
"""bug4 复刻：左划 backfill 灵不灵 ×（无指标/有指标）对照。"""
import os, json, urllib.request
from playwright.sync_api import sync_playwright

TOKEN = os.environ.get("AK_TOKEN", "")
BASE = "http://127.0.0.1:8766"
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def req(method, path, body=None):
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body else None,
                               headers=H, method=method)
    try: return json.load(urllib.request.urlopen(r))
    except Exception as e: return {"err": str(e)}

req("POST", "/api/board", {"id": "bf", "symbol": "BTC/USDT", "source": "datasource/mock_btc",
                           "params": {"days": 150}, "poll_s": 30})
logs = []
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox", "--disable-gpu"])
    pg = br.new_page(viewport={"width": 1600, "height": 1000})
    pg.on("console", lambda m: logs.append(m.text[:220]))
    pg.goto("http://127.0.0.1:8765/", wait_until="load")
    pg.wait_for_timeout(5000)

    def drag_left(n=60):
        pg.mouse.move(700, 300)
        pg.mouse.down(); pg.mouse.move(701, 300); pg.mouse.up()   # set userTouched
        for _ in range(n):
            pg.mouse.wheel(0, 400)
            pg.wait_for_timeout(250)

    print("=== 无指标左划 ===")
    drag_left()
    req("POST", "/api/indicator", {"board_id": "bf", "timeframe": "1d", "script": "indicator/sma"})
    pg.wait_for_timeout(3000)
    print("=== 有指标左划 ===")
    drag_left()
    pg.wait_for_timeout(2000)
    pg.screenshot(path='tools/smoke_bug5.png')
    br.close()
for l in logs[:40]: print('LOG|', l)
d = req("GET", "/api/board/bf/kline?timeframe=1d") if False else None
print("boards:", [(b["id"], req("GET", f"/api/overview?board_id={b['id']}&timeframe=1d").get("bars")) for b in req("GET", "/api/boards").get("boards", [])])
