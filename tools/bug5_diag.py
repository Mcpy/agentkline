#!/usr/bin/env python3
"""bug5 精测：__akDump 前后对照（前端活体数组 vs feed 服务快照）。"""
import json
from playwright.sync_api import sync_playwright

def dump(pg, tag):
    try:
        d = pg.evaluate("window.__akDump ? window.__akDump() : null")
    except Exception as e:
        print(tag, "eval err", e); return
    if not d:
        print(tag, "no dump"); return
    print(f"--- {tag} ---")
    print(f"  state.ohlcv: n={d['bars']} first={d['barsFirst']} last={d['barsLast']}")
    for i in d["inds"]:
        print(f"  ind {i['id']}: subplot={i['subplot']} vals={i['vals']} lines={i['lines']}")
    for e in d["emitted"]:
        print(f"  emit {e['g']}: pts={e['n']} t0={e['t0']} t1={e['t1']}")
    served = d["served"][-3:]
    for s in served:
        print(f"  feed.load served: n={s['n']} first={s['first']} last={s['last']}")

with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox", "--disable-gpu"])
    pg = br.new_page(viewport={"width": 1600, "height": 1000})
    errs = []
    pg.on("console", lambda m: errs.append(m.text[:160]) if m.type == "error" else None)
    pg.goto("http://127.0.0.1:8765/", wait_until="load")
    pg.wait_for_timeout(5000)
    dump(pg, "加载后（未左划）")
    # 左划到左缘触发 backfill
    pg.mouse.move(700, 300)
    pg.mouse.down(); pg.mouse.move(701, 300); pg.mouse.up()
    for _ in range(80):
        pg.mouse.wheel(0, 400)
        pg.wait_for_timeout(150)
    pg.wait_for_timeout(3000)
    dump(pg, "左划触发 backfill 后")
    print("--- console errors ---")
    print("\n".join(errs[:6]) or "(none)")
    pg.screenshot(path="tools/bug5_diag.png")
    br.close()
