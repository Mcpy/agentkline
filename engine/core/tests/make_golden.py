"""生成 golden 快照：`python engine/core/tests/make_golden.py`（改了口径就跑一次并 review diff）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _util import EXPECTED, build, spec  # noqa: E402

from agentkline_engine.registry import get_engine  # noqa: E402

GOLDEN = ("ma_long", "ma_short", "stock_both_protection")


def main():
    EXPECTED.mkdir(parents=True, exist_ok=True)
    for name in GOLDEN:
        req = build(name)
        result = get_engine(req.engine).run(req).to_dict()
        out = EXPECTED / f"{name}.result.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        print(f"{name}: {len(result['fills'])} fills, {len(result['trades'])} trades -> {out}")


if __name__ == "__main__":
    main()
