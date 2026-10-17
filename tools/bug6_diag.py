#!/usr/bin/env python3
"""bug6 精测：悬停主图/副图时，主图图例 vs 副图图例 谁跟随。"""
from playwright.sync_api import sync_playwright

def legends(pg):
    return pg.evaluate("""() => {
        const main = document.querySelector('#main-chart .legend');
        const subs = [...document.querySelectorAll('.legend.sub')].map(e => e.innerText.replace(/\\n/g,' | '));
        return { main: main ? main.innerText.replace(/\\n/g,' | ') : null, subs };
    }""")

with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox", "--disable-gpu"])
    pg = br.new_page(viewport={"width": 1600, "height": 1000})
    pg.goto("http://127.0.0.1:8765/", wait_until="load")
    pg.wait_for_timeout(5000)
    box = pg.evaluate("() => { const r = document.getElementById('main-chart').getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; }")
    sub = pg.evaluate("() => { const e = document.querySelector('.legend.sub'); if(!e) return null; const r = e.parentElement.getBoundingClientRect(); const inMain = !!e.closest('#main-chart'); return {x:r.x,y:r.y,w:r.width,h:r.height,inMain}; }")
    print("main box", box, "sub box", sub)

    print("== 悬停主图 x1 =="); pg.mouse.move(box['x']+box['w']*0.3, box['y']+box['h']*0.5); pg.wait_for_timeout(400); a=legends(pg); print(" main:", a['main']); print(" subs:", a['subs'])
    print("== 悬停主图 x2 =="); pg.mouse.move(box['x']+box['w']*0.6, box['y']+box['h']*0.5); pg.wait_for_timeout(400); b=legends(pg); print(" main:", b['main']); print(" subs:", b['subs'])
    print("主图跟随?", a['main']!=b['main'], "| 副图跟随?", a['subs']!=b['subs'])
    if sub:
        print("== 悬停副图 x1 =="); pg.mouse.move(sub['x']+sub['w']*0.3, sub['y']+40); pg.wait_for_timeout(400); c=legends(pg); print(" main:", c['main']); print(" subs:", c['subs'])
        print("== 悬停副图 x2 =="); pg.mouse.move(sub['x']+sub['w']*0.6, sub['y']+40); pg.wait_for_timeout(400); d=legends(pg); print(" main:", d['main']); print(" subs:", d['subs'])
        print("副图悬停: 主图跟随?", c['main']!=d['main'], "| 副图跟随?", c['subs']!=d['subs'])
    br.close()
