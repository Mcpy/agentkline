#!/usr/bin/env python3
"""AgentKline UI smoke (v0.5.4) — 6 browser checks on a disposable instance.

Why this exists: test_e2e.py covers the API/MCP surface, not the browser UI.
These five checks protect the surfaces that 0.5.3/0.5.4 changed by hand:

  1. indicator library opens (75 builtins, fixed nav entries) + search filters
  2. clicking a card adds one instance + "added" count updates
  3. favorite survives a page reload
  4. recently-used order follows the last successful add
  5. VPVR layer chip: on → survives reload → off (per-board, localStorage)
  6. latest price outside the visible price range pins to pane top/bottom
     (▲ / ▼) and disappears again when back in range

It boots a temporary server on free localhost ports with an EMPTY custom
scripts root (the 75 builtin entries), creates a mock board, drives headless
Chromium, then removes the temp dir and kills the server. No live board is
touched.

Prereqs:
    pip install -e ".[dev]"           # adds playwright
    python -m playwright install chromium
  or point at an existing Chrome/Chromium:
    AK_CHROMIUM=/path/to/chrome python tools/ui_smoke.py

Usage:
    python tools/ui_smoke.py
    AK_CHROMIUM=/usr/bin/chromium python tools/ui_smoke.py
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD_ID = "uismoke"
BOARD = {
    "id": BOARD_ID,
    "symbol": "AAA/USDT",
    "source": "datasource/mock_btc",
    "params": {"days": 60},
}


# ---------------------------------------------------------------- HTTP helpers
def _get(url: str, timeout: float = 2.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _post(url: str, payload: dict, timeout: float = 30.0):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _delete(url: str, timeout: float = 5.0):
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_http(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


# ---------------------------------------------------------------- temp server
class TempServer:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ak_ui_smoke_"))
        (self.tmp / "scripts").mkdir()
        self.web_port = _free_port()
        self.agent_port = _free_port()
        self.base = f"http://127.0.0.1:{self.web_port}"
        self.log_path = self.tmp / "server.log"
        self.log = open(self.log_path, "w", encoding="utf-8")
        env = os.environ.copy()
        env.update({
            "AGENTKLINE_WEB_HOST": "127.0.0.1",
            "AGENTKLINE_WEB_PORT": str(self.web_port),
            "AGENTKLINE_AGENT_HOST": "127.0.0.1",
            "AGENTKLINE_AGENT_PORT": str(self.agent_port),
            "AGENTKLINE_SCRIPTS_DIR": str(self.tmp / "scripts"),
        })
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "agentkline.api.app"],
            cwd=str(ROOT),
            env=env,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )

    def wait_ready(self) -> bool:
        return _wait_http(self.base + "/api/config", timeout=35)

    def tail(self, n: int = 40) -> str:
        try:
            self.log.flush()
            return "\n".join(self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
        except Exception:
            return ""

    def stop(self):
        try:
            self.log.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------- browser
def _chrome_candidates() -> list[str]:
    out: list[str] = []
    for key in ("AK_CHROMIUM", "PLAYWRIGHT_CHROMIUM_EXECUTABLE", "CHROME_PATH"):
        p = os.environ.get(key)
        if p:
            out.append(p)
    out += [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    cache = Path.home() / ".cache" / "ms-playwright"
    # The headless shell has fewer native-library deps than full Chromium.
    out += sorted(glob.glob(str(cache / "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")),
                  reverse=True)
    out += sorted(glob.glob(str(cache / "chromium-*/chrome-linux*/chrome")), reverse=True)
    seen, uniq = set(), []
    for p in out:
        if p and p not in seen and Path(p).is_file():
            seen.add(p)
            uniq.append(p)
    return uniq


def _browser_env() -> dict:
    env = os.environ.copy()
    libs = env.get("AK_CHROMIUM_LIBS") or "/tmp/syslibs/root/usr/lib/x86_64-linux-gnu"
    if Path(libs).is_dir():
        old = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = libs + (":" + old if old else "")
    return env


def _launch_browser(p):
    args = ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
    env = _browser_env()
    last = None
    for exe in _chrome_candidates():
        try:
            return p.chromium.launch(executable_path=exe, headless=True, args=args, env=env)
        except Exception as e:  # try the next candidate (missing libs, etc.)
            last = e
            print(f"  (browser candidate failed: {Path(exe).name}: {str(e).splitlines()[0]})")
    try:
        return p.chromium.launch(headless=True, args=args, env=env)
    except Exception:
        raise RuntimeError(
            "no usable Chromium/Chrome found; run `python -m playwright install chromium` "
            "or set AK_CHROMIUM=/path/to/chrome"
        ) from last


# ---------------------------------------------------------------- page helpers
def _wait_app(page):
    page.wait_for_function(
        """() => {
            try {
                const c = window.__ak && window.__ak.chart;
                return !!(c && c.orchestrator.renderer.scene.bars.length);
            } catch (e) { return false; }
        }""",
        timeout=25000,
    )


def _open_lib(page):
    if page.locator(".ind-lib-modal").count() == 0:
        page.locator(".ind-add").click()
    page.wait_for_selector(".ind-lib-modal", timeout=8000)
    page.wait_for_selector(".ind-lib-card", timeout=10000)


def _close_lib(page):
    if page.locator(".ind-lib-modal").count():
        page.locator(".ind-lib-close").click()
        page.wait_for_selector(".ind-lib-modal", state="detached", timeout=5000)


def _nav_text(page) -> str:
    return page.locator(".ind-lib-nav").inner_text()


def _indicator_scripts(base: str) -> set[str]:
    data = _get(f"{base}/api/indicators?board_id={BOARD_ID}&timeframe=1d", timeout=5)
    return {(v.get("script") or "") for v in (data.get("indicators") or {}).values()}


def _wait_until(fn, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(0.15)
    return False


# ---------------------------------------------------------------- checks
def run_checks(page, base: str) -> tuple[int, int]:
    passed = failed = 0

    def check(name: str, ok: bool, detail="") -> None:
        nonlocal passed, failed
        if ok:
            passed += 1
            print(f"  ✅ {name}")
        else:
            failed += 1
            print(f"  ❌ {name} {detail}")

    # 1) library opens + search filters
    _open_lib(page)
    nav = _nav_text(page)
    total = page.locator(".ind-lib-card").count()
    search = page.locator(".ind-lib-search")
    search.fill("bollinger")
    page.wait_for_timeout(250)
    scripts = page.locator(".ind-lib-card").evaluate_all("els => els.map(e => e.dataset.script)")
    check("指标库：打开 + 搜索过滤", total == 75
          and all(x in nav for x in ("全部", "收藏", "最近使用", "已添加"))
          and set(scripts) == {"indicator/bollinger_bands", "indicator/percent_b", "indicator/bandwidth"},
          f"total={total} nav={nav[:80]} scripts={scripts}")

    # 2) add one instance
    search.fill("")
    page.wait_for_timeout(200)
    card = page.locator('[data-script="indicator/bollinger_bands"]')
    card.locator(".ind-lib-card-main").click()
    # server result can land before the library re-renders: wait for the UI, not just API
    page.wait_for_function(
        """() => {
            const nav = [...document.querySelectorAll('.ind-lib-nav-item')]
                .some(e => e.textContent.replace(/\\s+/g, ' ').trim() === '已添加 1');
            const badge = document.querySelector(
                '[data-script="indicator/bollinger_bands"] .ind-lib-badge');
            return nav && badge && badge.textContent.trim() === '1';
        }""",
        timeout=10000,
    )
    added = "indicator/bollinger_bands" in _indicator_scripts(base)
    badge = card.locator(".ind-lib-badge").inner_text() if card.locator(".ind-lib-badge").count() else ""
    check("加实例：API + 计数", added and badge == "1",
          f"added={added} badge={badge} nav={_nav_text(page)[:80]}")

    # 3) favorite survives reload
    card.locator(".ind-lib-fav").click()
    page.wait_for_function(
        "() => (localStorage.getItem('ak.indicator.prefs.v1') || '').includes('bollinger_bands')",
        timeout=3000,
    )
    fav_cls = card.locator(".ind-lib-fav").get_attribute("class") or ""
    page.reload(wait_until="domcontentloaded")
    _wait_app(page)
    _open_lib(page)
    reload_nav = _nav_text(page)
    reload_cls = page.locator('[data-script="indicator/bollinger_bands"] .ind-lib-fav').get_attribute("class") or ""
    check("收藏：刷新后仍保留", "on" in fav_cls and "收藏 1" in reload_nav and "on" in reload_cls,
          f"nav={reload_nav[:80]} cls={reload_cls}")

    # 4) recently-used order
    page.locator('[data-script="indicator/ema"] .ind-lib-card-main').click()
    added_ema = _wait_until(lambda: "indicator/ema" in _indicator_scripts(base))
    page.wait_for_timeout(300)
    pref = page.evaluate("() => JSON.parse(localStorage.getItem('ak.indicator.prefs.v1') || '{}')")
    recent = pref.get("recent") or []
    page.locator(".ind-lib-search").fill("")
    page.wait_for_timeout(150)
    page.locator(".ind-lib-nav-item").filter(has_text="最近使用").click()
    page.wait_for_timeout(200)
    order = page.locator(".ind-lib-card").evaluate_all("els => els.map(e => e.dataset.script)")
    check("最近使用：按最后添加倒序", added_ema
          and recent[:2] == ["indicator/ema", "indicator/bollinger_bands"]
          and order[:2] == ["indicator/ema", "indicator/bollinger_bands"],
          f"recent={recent[:4]} order={order[:4]}")

    # 5) VPVR layer chip: on → survives reload → off（0.6.0 起去掉 ⚙/设置，与 Vol 一样只有开关）
    _close_lib(page)
    chip = page.locator("#chart-layer-vpvr")
    off_width = (chip.bounding_box() or {}).get("width")
    chip.click()
    page.wait_for_function(
        "() => window.__ak.chart.presentNativeIndicators().includes('vpvr')",
        timeout=4000,
    )
    chip_on = "on" in (chip.get_attribute("class") or "")
    page.wait_for_timeout(300)
    on_width = (chip.bounding_box() or {}).get("width")
    fixed_width = bool(off_width and on_width and abs(off_width - on_width) < 0.5)
    legend_hidden = page.evaluate("""() => [...document.querySelectorAll('#main-chart span')]
        .filter(e => e.children.length === 0 && e.textContent.trim() === 'VRVP'
            && e.offsetParent !== null).length""")
    chip_box = chip.bounding_box()
    ohlc_box = page.locator("#ohlc-legend").bounding_box()
    aligned = bool(chip_box and ohlc_box
                   and abs((chip_box["y"] + chip_box["height"] / 2)
                           - (ohlc_box["y"] + ohlc_box["height"] / 2)) <= 2)
    space_ok = bool(chip_box and ohlc_box
                    and chip_box["y"] - ohlc_box["y"] >= 4
                    and (ohlc_box["y"] + ohlc_box["height"])
                        - (chip_box["y"] + chip_box["height"]) >= 4)
    page.evaluate("""() => {
        const h = (window.__ak.chart.indicators() || []).find(x => x.nativeType === 'vpvr');
        if (h) h.setInputs({ rows: 40 });
    }""")
    page.wait_for_timeout(300)
    page.reload(wait_until="domcontentloaded")
    _wait_app(page)
    page.wait_for_selector("#chart-layer-vpvr", timeout=8000)
    page.wait_for_function(
        "() => window.__ak.chart.presentNativeIndicators().includes('vpvr')",
        timeout=5000,
    )
    chip_after = "on" in (page.locator("#chart-layer-vpvr").get_attribute("class") or "")
    legend_after = page.evaluate("""() => [...document.querySelectorAll('#main-chart span')]
        .filter(e => e.children.length === 0 && e.textContent.trim() === 'VRVP'
            && e.offsetParent !== null).length""")
    rows_after = page.evaluate("""() => {
        const h = (window.__ak.chart.indicators() || []).find(x => x.nativeType === 'vpvr');
        return h ? h.inputValues().rows : null;
    }""")
    page.locator("#chart-layer-vpvr").click()
    page.wait_for_function(
        "() => !window.__ak.chart.presentNativeIndicators().includes('vpvr')",
        timeout=4000,
    )
    chip_off = "on" not in (page.locator("#chart-layer-vpvr").get_attribute("class") or "")
    check("VPVR 图层：固定宽度 / 图例隐藏 / OHLC 居中留白 / 刷新恢复 / 参数保留 / 关",
          chip_on and fixed_width and legend_hidden == 0 and aligned and space_ok
          and chip_after and legend_after == 0 and rows_after == 40 and chip_off,
          f"on={chip_on} width={off_width}/{on_width} legend={legend_hidden} "
          f"aligned={aligned} space={space_ok} "
          f"afterReload={chip_after}/{legend_after} rows={rows_after} off={chip_off}")

    # 6) out-of-range last-price pin
    # 真实拖价格轴在无头环境里不稳定，这里用适配层内部探针 + setManualScale 触发；
    # 覆盖的是同一条 chrome 绘制路径（越界判定/贴边/箭头/回区间隐藏）。
    _close_lib(page)
    last = page.evaluate("() => window.__ak.chart.orchestrator.renderer.scene.bars.slice(-1)[0].close")
    page.evaluate(
        """(last) => {
            const r = window.__ak.chart.orchestrator.renderer;
            const p = [...r.scene.panes.values()].find(x => x.kind === 'price');
            r.setManualScale(p, { min: last - 10000, max: last - 5000, invert: false, log: false });
        }""",
        last,
    )
    page.wait_for_function(
        "() => { const p = window.__ak.lastPricePin && window.__ak.lastPricePin(); return p && p.text.startsWith('▲'); }",
        timeout=4000,
    )
    above = page.evaluate("() => window.__ak.lastPricePin()")
    page.evaluate(
        """(last) => {
            const r = window.__ak.chart.orchestrator.renderer;
            const p = [...r.scene.panes.values()].find(x => x.kind === 'price');
            r.setManualScale(p, { min: last + 5000, max: last + 10000, invert: false, log: false });
        }""",
        last,
    )
    page.wait_for_function(
        "() => { const p = window.__ak.lastPricePin && window.__ak.lastPricePin(); return p && p.text.startsWith('▼'); }",
        timeout=4000,
    )
    below = page.evaluate("() => window.__ak.lastPricePin()")
    page.evaluate(
        """(last) => {
            const r = window.__ak.chart.orchestrator.renderer;
            const p = [...r.scene.panes.values()].find(x => x.kind === 'price');
            r.setManualScale(p, { min: last - 20000, max: last + 20000, invert: false, log: false });
        }""",
        last,
    )
    page.wait_for_function(
        "() => !(window.__ak.lastPricePin && window.__ak.lastPricePin())",
        timeout=4000,
    )
    check("最新价越界：贴顶 ▲ / 贴底 ▼ / 回区间隐藏",
          above["top"] <= 2 and above["width"] > 0 and below["top"] > 100 and below["width"] > 0,
          f"above={above} below={below}")

    return passed, failed


# ---------------------------------------------------------------- main
def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 playwright：先 `pip install -e \".[dev]\"`（或 `uv pip install playwright`）", file=sys.stderr)
        return 2

    server = TempServer()
    browser = None
    page = None
    page_errors: list[str] = []
    try:
        if not server.wait_ready():
            print("临时服务启动失败；日志：\n" + server.tail(), file=sys.stderr)
            return 2
        try:
            _post(server.base + "/api/board", BOARD)
        except urllib.error.HTTPError as e:
            print(f"建板失败 HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}", file=sys.stderr)
            print(server.tail(), file=sys.stderr)
            return 2

        print(f"临时实例 {server.base}（board={BOARD_ID}）")
        with sync_playwright() as p:
            browser = _launch_browser(p)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda e: page_errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: page_errors.append(f"console.{m.type}: {m.text}")
                    if m.type == "error" else None)
            page.goto(server.base + "/?lang=zh", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector(".ind-add", timeout=15000)
            _wait_app(page)

            print("\nUI smoke（6 条）")
            passed, failed = run_checks(page, server.base)

            # Console errors are a hard failure, but not a sixth check.
            noise = [e for e in page_errors if "favicon" not in e]
            if noise:
                failed += 1
                print("  ❌ 浏览器 console/page error：")
                for e in noise[:5]:
                    print("     " + e[:300])

            print(f"\nResults: {passed} passed, {failed} failed")
            if failed:
                try:
                    shot = Path(tempfile.gettempdir()) / "ak_ui_smoke_fail.png"
                    page.screenshot(path=str(shot), full_page=True)
                    print(f"失败截图：{shot}")
                except Exception:
                    pass
                print("\n服务端日志尾部：\n" + server.tail(60))
            return 0 if failed == 0 else 1
    finally:
        try:
            if page:
                page.close()
        except Exception:
            pass
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        try:
            _delete(server.base + f"/api/board/{BOARD_ID}")
        except Exception:
            pass
        server.stop()


if __name__ == "__main__":
    sys.exit(main())
