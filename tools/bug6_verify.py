#!/usr/bin/env python3
"""bug6 验证：UTC+8 时区下，悬停主图区/副图区，主图例与副图例是否统一跟随十字线。"""
from playwright.sync_api import sync_playwright

def legends(pg):
    return pg.evaluate("""() => {
        const m = document.querySelector('#main-chart .legend');
        const subs = [...document.querySelectorAll('.legend.sub')].map(e => e.innerText.replace(/\\n/g,' '));
        return { main: m ? m.innerText.replace(/\\n/g,' ') : null, subs };
    }""")

with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox", "--disable-gpu"])
    ctx = br.new_context(viewport={"width": 1600, "height": 1000}, timezone_id="Asia/Shanghai")
    pg = ctx.new_page()
    pg.goto("http://127.0.0.1:8765/", wait_until="load")
    pg.wait_for_timeout(6000)
    box = pg.evaluate("() => { const r = document.getElementById('main-chart').getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; }")
    print("chart box", box)

    def hover(fx, fy, tag):
        pg.mouse.move(box['x'] + box['w'] * fx, box['y'] + box['h'] * fy)
        pg.wait_for_timeout(350)
        d = legends(pg)
        print(f"[{tag}] main: {d['main'][:95]}")
        print(f"[{tag}] subs: {d['subs']}")
        return d

    a = hover(0.30, 0.35, "主图区 x1")
    b = hover(0.60, 0.35, "主图区 x2")
    print(">> 主图区悬停: 主图例跟随?", a['main'] != b['main'], "| 副图例跟随?", a['subs'] != b['subs'])
    c = hover(0.30, 0.93, "副图区 x1")
    d = hover(0.60, 0.93, "副图区 x2")
    print(">> 副图区悬停: 主图例跟随?", c['main'] != d['main'], "| 副图例跟随?", c['subs'] != d['subs'])
    pg.mouse.move(10, 10); pg.wait_for_timeout(400)
    e = legends(pg)
    print(">> 移开后回最新:", e['main'][:80])
    pg.screenshot(path="tools/bug6_verify.png")
    br.close()
