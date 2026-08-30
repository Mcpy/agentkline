#!/usr/bin/env python3
"""
AgentKline - 端到端测试脚本
运行: python test_e2e.py [--port 8001]
"""
import sys
import json
import argparse
import requests

def test(port: int):
    base = f"http://localhost:{port}"
    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal passed, failed
        if condition:
            print(f"  ✅ {name}")
            passed += 1
        else:
            print(f"  ❌ {name} {detail}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"AgentKline E2E Tests (port={port})")
    print(f"{'='*60}\n")

    # === 1. Board Management ===
    print("📋 Board Management")
    r = requests.post(f"{base}/api/board", json={"id": "test_board", "name": "Test", "intervals": ["1d", "4h"]})
    check("Create board", r.status_code == 200, r.text)

    r = requests.get(f"{base}/api/boards")
    boards = r.json().get("boards", [])
    check("List boards", any(b["id"] == "test_board" for b in boards))

    r = requests.get(f"{base}/api/board/test_board")
    check("Switch board", r.status_code == 200)

    # === 2. Data Loading ===
    print("\n📊 Data Loading")
    r = requests.post(f"{base}/api/board/test_board/timeframe/1d/datasource",
                      json={"path": "mock_btc_data.py", "params": {"days": 50}})
    check("Load data via script", r.status_code == 200 and r.json().get("count") == 50, r.text)

    r = requests.get(f"{base}/api/state?board_id=test_board&timeframe=1d")
    state = r.json()
    check("State has OHLCV", len(state.get("ohlcv", [])) == 50)

    # === 3. Indicators ===
    print("\n📈 Indicators")
    r = requests.post(f"{base}/api/run-script?board_id=test_board&timeframe=1d",
                      json={"path": "sma.py", "params": {"period": 10}, "save_as": "indicator", "indicator_name": "sma_10"})
    check("Add SMA indicator", r.status_code == 200, r.text)

    r = requests.post(f"{base}/api/indicator?board_id=test_board&timeframe=1d",
                      json={"name": "direct_line", "type": "line", "values": [None]*20 + [1.0]*30, "style": {"color": "#ff0000"}})
    check("Push indicator directly", r.status_code == 200, r.text)

    # Test override
    r = requests.post(f"{base}/api/indicator?board_id=test_board&timeframe=1d",
                      json={"name": "direct_line", "type": "line", "values": [None]*10 + [2.0]*40, "replace": True})
    check("Override indicator (replace=true)", r.status_code == 200, r.text)

    r = requests.post(f"{base}/api/indicator?board_id=test_board&timeframe=1d",
                      json={"name": "direct_line", "type": "line", "values": [3.0], "replace": False})
    check("Reject override (replace=false)", r.status_code == 400 and "INDICATOR_EXISTS" in r.text)

    # Multi-line
    r = requests.post(f"{base}/api/indicator?board_id=test_board&timeframe=1d",
                      json={"name": "multi", "lines": [
                          {"name": "a", "type": "line", "values": [1.0]*50, "style": {"color": "#00ff00"}},
                          {"name": "b", "type": "histogram", "values": [0.5]*50, "style": {"color": "#0000ff"}}
                      ]})
    check("Multi-line indicator", r.status_code == 200, r.text)

    # === 4. Subplots ===
    print("\n📉 Subplots")
    r = requests.post(f"{base}/api/subplot?board_id=test_board&timeframe=1d",
                      json={"name": "vol_panel", "height": 100, "title": "Volume"})
    check("Create subplot", r.status_code == 200, r.text)

    r = requests.get(f"{base}/api/subplots?board_id=test_board&timeframe=1d")
    check("List subplots", any(s["name"] == "vol_panel" for s in r.json().get("subplots", [])))

    r = requests.put(f"{base}/api/subplot/vol_panel?board_id=test_board&timeframe=1d",
                     json={"height": 200})
    check("Update subplot", r.status_code == 200 and r.json().get("height") == 200)

    # === 5. Markers ===
    print("\n📍 Markers")
    r = requests.post(f"{base}/api/markers?board_id=test_board&timeframe=1d",
                      json={"markers": [{"time": 1755000000000, "position": "aboveBar", "color": "#ff0000", "shape": "circle", "text": "test"}]})
    check("Push markers", r.status_code == 200, r.text)

    r = requests.get(f"{base}/api/state?board_id=test_board&timeframe=1d")
    check("Markers in state", len(r.json().get("markers", [])) == 1)

    # === 6. Timeframe Management ===
    print("\n⏱️ Timeframe Management")
    r = requests.post(f"{base}/api/board/test_board/timeframe", json={"interval": "1w"})
    check("Create timeframe", r.status_code == 200, r.text)

    r = requests.get(f"{base}/api/board/test_board/timeframes")
    check("List timeframes", "1w" in r.json().get("timeframes", []))

    r = requests.get(f"{base}/api/board/test_board/timeframe/1w")
    check("Switch timeframe", r.status_code == 200)

    r = requests.delete(f"{base}/api/board/test_board/timeframe/1w")
    check("Delete timeframe", r.status_code == 200)

    # === 7. Indicator Delete ===
    print("\n🗑️ Cleanup")
    r = requests.delete(f"{base}/api/indicator/direct_line?board_id=test_board&timeframe=1d")
    check("Delete indicator", r.status_code == 200)

    r = requests.delete(f"{base}/api/subplot/vol_panel?board_id=test_board&timeframe=1d")
    check("Delete subplot", r.status_code == 200)

    r = requests.delete(f"{base}/api/board/test_board")
    check("Delete board", r.status_code == 200)

    # === Summary ===
    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
    print(f"{'='*60}\n")

    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    success = test(args.port)
    sys.exit(0 if success else 1)
