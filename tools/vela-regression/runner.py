#!/usr/bin/env python3
"""Vela PoC runner：headless chromium 跑实验页，console + DOM + 截图存证。
用法：python poc_runner.py p0-probe [p1-lines ...]
"""
import sys, os, json, glob
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8799/"
EV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evidence")
os.makedirs(EV, exist_ok=True)

def _launch(p):
    """本机/缓存 Chromium 解析（与 tools/ui_smoke.py 同策略）：
    AK_CHROMIUM > 系统 chrome > playwright 缓存 headless shell > 缓存 chromium。
    缓存浏览器缺系统库时，可用 AK_CHROMIUM_LIBS 指到解包目录（默认 /tmp/syslibs/...）。"""
    args = ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
    env = os.environ.copy()
    libs = env.get("AK_CHROMIUM_LIBS") or "/tmp/syslibs/root/usr/lib/x86_64-linux-gnu"
    if Path(libs).is_dir():
        old = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = libs + (":" + old if old else "")
    cands = [env.get("AK_CHROMIUM"), "/usr/bin/chromium", "/usr/bin/chromium-browser",
             "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"]
    cache = Path.home() / ".cache" / "ms-playwright"
    cands += sorted(glob.glob(str(cache / "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")), reverse=True)
    cands += sorted(glob.glob(str(cache / "chromium-*/chrome-linux*/chrome")), reverse=True)
    seen = set()
    for exe in cands:
        if not exe or exe in seen or not Path(exe).is_file():
            continue
        seen.add(exe)
        try:
            return p.chromium.launch(executable_path=exe, args=args, env=env)
        except Exception as e:
            print(f"  browser candidate failed: {Path(exe).name}: {str(e).splitlines()[0]}")
    return p.chromium.launch(args=args, env=env)


def run(page_name):
    logs = []
    with sync_playwright() as p:
        br = _launch(p)
        pg = br.new_page(viewport={"width": 1600, "height": 1000})
        pg.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"))
        pg.on("pageerror", lambda e: logs.append(f"[pageerror] {e}"))
        pg.goto(BASE + page_name + ".html", wait_until="load")
        pg.wait_for_timeout(int(os.environ.get("POC_WAIT", "9000")))
        dom = {}
        for sel in ["#out", "#results", "#status", "#doc"]:
            try:
                el = pg.query_selector(sel)
                if el:
                    dom[sel] = el.inner_text()
            except Exception:
                pass
        move = os.environ.get("POC_MOVE")
        if move:
            x, y = [int(v) for v in move.split(",")]
            pg.mouse.move(x, y)
            pg.wait_for_timeout(600)
            pg.screenshot(path=os.path.join(EV, page_name + "_hover.png"))
            print("hover shot saved")
        click = os.environ.get("POC_CLICK")
        if click:
            x, y = [int(v) for v in click.split(",")]
            pg.mouse.click(x, y)
            pg.wait_for_timeout(1200)
            shot0 = os.path.join(EV, page_name + "_click.png")
            pg.screenshot(path=shot0)
            print("click shot:", shot0)
        shot = os.path.join(EV, page_name + ".png")
        pg.screenshot(path=shot)
        br.close()
    with open(os.path.join(EV, page_name + ".log"), "w") as f:
        f.write("\n".join(logs))
    with open(os.path.join(EV, page_name + ".dom.json"), "w") as f:
        json.dump(dom, f, ensure_ascii=False, indent=1)
    print(f"=== {page_name} ===")
    print("\n".join(logs)[:6000])
    for k, v in dom.items():
        print(f"--- DOM {k} ---\n{v[:4000]}")

if __name__ == "__main__":
    for name in sys.argv[1:] or ["p0-probe"]:
        run(name)
