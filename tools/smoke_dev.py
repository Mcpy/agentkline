#!/usr/bin/env python3
"""0.5.1-dev 自验：bug1 无闪铁证（rebuild=1/incr>=1）+ 乙案写回（_schema vela1）。"""
import os, json, urllib.request
from playwright.sync_api import sync_playwright

TOKEN = os.environ.get("AK_TOKEN", "")
BASE = "http://127.0.0.1:8786"
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def req(method, path, body=None):
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body else None,
                               headers=H, method=method)
    return json.load(urllib.request.urlopen(r))

req("POST", "/api/board", {"id": "dev", "symbol": "BTC/USDT", "source": "datasource/mock_btc",
                           "params": {"days": 120}, "poll_s": 5})
req("POST", "/api/indicator", {"board_id": "dev", "timeframe": "1d", "script": "indicator/sma"})

logs = []
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox", "--disable-gpu"])
    pg = br.new_page(viewport={"width": 1600, "height": 1000})
    pg.on("console", lambda m: logs.append(m.text[:150]))
    pg.goto("http://127.0.0.1:8785/", wait_until="load")
    pg.wait_for_timeout(14000)          # ≥2 轮 5s 轮询
    # 鼠标画线验乙案写回
    pg.mouse.click(20, 181); pg.wait_for_timeout(600)
    pg.mouse.click(700, 300); pg.wait_for_timeout(1500)
    pg.screenshot(path="tools/smoke_dev.png")
    br.close()

reb = [l for l in logs if l.startswith('[ak] rebuild#')]
inc = [l for l in logs if l.startswith('[ak] incr#')]
print('rebuild 次数:', len(reb), reb[:3])
print('incr 次数:', len(inc), inc[:3])
print('bug1 判定:', '无闪✅' if len(reb) == 1 and len(inc) >= 1 else '仍闪❌')
d = req("GET", "/api/drawings?board_id=dev&timeframe=1d")
vd = [x for x in d['drawings'] if x.get('_schema') == 'vela1']
print('乙案写回条目:', len(vd), json.dumps(vd[0], ensure_ascii=False)[:200] if vd else 'NONE')
