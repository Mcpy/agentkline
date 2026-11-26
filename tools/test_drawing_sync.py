#!/usr/bin/env python3
"""0.7.4 画线同步验收（D1–D6）：Vela 0.10.19「仅同品种」上游变更下的本端同步语义。

D1 同品种跨周期可见（showOn 缺省=全周期）
D2 异品种隔离（A 板的线不出现在 B 板）
D3 多端实时同步（两个浏览器会话同板，REST 增删改双方一致）
D4 首启/切板 fromJSON 装载，无重复加载
D5 批量导入/删除一次广播，前端幂等
D6 已有 id 走 update 保留撤销栈

运行：.venv/bin/python tools/test_drawing_sync.py
复用 ui_smoke 的临时实例与浏览器解析，不触碰 live。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_smoke import TempServer, _get, _post, _launch_browser  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("  ✅ " if ok else "  ❌ ") + name + (f"  [{detail}]" if detail and not ok else ""))


def wait_count(page, n, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if page.evaluate("window.__ak ? window.__ak.drawings().length : -1") == n:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def switch_board(server, bid):
    _get(server.base + f"/api/board/{bid}")


def switch_tf(server, bid, tf):
    _get(server.base + f"/api/board/{bid}/timeframe/{tf}")


def add_hline(server, bid, price, **kw):
    return _post(server.base + "/api/drawing",
                 {"board_id": bid, "type": "hline", "anchors": [{"price": price}], **kw})


def main():
    server = TempServer()
    if not server.wait_ready():
        print("临时服务启动失败：\n" + server.tail()); return 2
    A, B = "dsync_a", "dsync_b"
    for bid, sym in ((A, "AAA/USDT"), (B, "BBB/USDT")):
        _post(server.base + "/api/board",
              {"id": bid, "symbol": sym, "source": "datasource/mock_btc", "params": {"days": 300}})
    # mock_btc 建板即自动注入其全部支持周期（1d/1w），无需手动 create_timeframe
    switch_board(server, A)

    with sync_playwright() as p:
        br = _launch_browser(p)
        pg = br.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(server.base, wait_until="load")
        pg.wait_for_function("window.__ak && window.__ak.chart", timeout=30000)
        pg.wait_for_timeout(1500)

        # D1 同品种跨周期
        r = add_hline(server, A, 30000)
        d1_id = r.get("id")
        ok = wait_count(pg, 1)
        switch_tf(server, A, "1w")
        ok = ok and wait_count(pg, 1)
        switch_tf(server, A, "1d")
        ok = ok and wait_count(pg, 1)
        check("D1 同品种跨周期可见", ok and d1_id)

        # D2 异品种隔离
        switch_board(server, B)
        ok = wait_count(pg, 0)
        add_hline(server, B, 40000)
        ok = ok and wait_count(pg, 1)
        switch_board(server, A)
        ok = ok and wait_count(pg, 1)   # A 仍只有自己的 1 条
        check("D2 异品种隔离", ok)

        # D3 多端同步
        pg2 = br.new_page(viewport={"width": 1440, "height": 900})
        pg2.goto(server.base, wait_until="load")
        pg2.wait_for_function("window.__ak && window.__ak.chart", timeout=30000)
        pg2.wait_for_timeout(1500)
        switch_board(server, A)
        ok = wait_count(pg, 1) and wait_count(pg2, 1)
        r2 = add_hline(server, A, 31000)
        ok = ok and wait_count(pg, 2) and wait_count(pg2, 2)
        _post(server.base + f"/api/drawing/{r2['id']}", {"board_id": A, "style": {"lineColor": "#ff8800"}})
        pg.wait_for_timeout(800)
        _post(server.base + "/api/drawings/delete", {"board_id": A, "ids": [r2["id"]]})
        ok = ok and wait_count(pg, 1) and wait_count(pg2, 1)
        check("D3 多端实时同步", ok)
        pg2.close()

        # D4 切板往返 fromJSON，无重复
        switch_board(server, B)
        wait_count(pg, 1)
        switch_board(server, A)
        ok = wait_count(pg, 1)
        switch_board(server, B)
        switch_board(server, A)
        ok = ok and wait_count(pg, 1)
        check("D4 切板装载无重复", ok)

        # D5 批量导入/删除
        items = [{"type": "hline", "anchors": [{"price": 32000 + i * 100}]} for i in range(3)]
        rb = _post(server.base + "/api/drawings", {"board_id": A, "items": items})
        ids = [d["id"] for d in (rb.get("drawings") or [])]
        ok = wait_count(pg, 4)
        _post(server.base + "/api/drawings/delete", {"board_id": A, "ids": ids})
        ok = ok and wait_count(pg, 1)
        check("D5 批量导入/删除", ok and len(ids) == 3, f"ids={ids}")

        # D6 update 保留撤销栈
        _post(server.base + f"/api/drawing/{d1_id}", {"board_id": A, "style": {"lineColor": "#00cc88"}})
        pg.wait_for_timeout(800)
        can_undo = pg.evaluate("window.__ak.chart.drawings.canUndo()")
        cnt = pg.evaluate("window.__ak.drawings().length")
        check("D6 update 保留撤销栈", can_undo and cnt == 1, f"canUndo={can_undo} count={cnt}")

        br.close()
    server.proc.terminate()
    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"\nResults: {passed} passed, {len(RESULTS) - passed} failed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
