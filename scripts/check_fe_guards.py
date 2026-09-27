#!/usr/bin/env python3
"""前端护栏两道门（v0.4.3 C）：
C1 import 图判环（0.4.1 循环绑定坏绑定教训：ws→watchlist→ui→ws 曾静默炸渲染）；
C2 跨模块导出名在本文件被调用但未 import 且未本地定义（老 bug1 教训：
   ui.js 调 renderChart / ws.js 调 refreshSearch 漏 import = ReferenceError 断链）。
用法：python scripts/check_fe_guards.py  → 违例打印并 exit 1；干净 exit 0。
"""
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"

IMPORT_RE = re.compile(r"import\s*\{([^}]*)\}\s*from\s*['\"]\.\/([\w\-]+)\.js['\"]")
EXPORT_FN_RE = re.compile(r"export\s+function\s+(\w+)")
EXPORT_LIST_RE = re.compile(r"export\s*\{([^}]*)\}")
DEF_RE = re.compile(r"^\s*(?:async\s+)?(?:function\s+(\w+)|const\s+(\w+)\s*=|let\s+(\w+)\s*=|var\s+(\w+)\s*=|class\s+(\w+))", re.M)


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//.*", "", src)
    return src


def main():
    files = sorted(SRC.glob("*.js"))
    exports = {}   # module -> set(names)
    imports = {}   # module -> set(names)
    bodies = {}
    defs = {}
    for f in files:
        raw = f.read_text(encoding="utf-8")
        mod = f.stem
        bodies[mod] = strip_comments(raw)
        imports[mod] = set()
        for names, _from in IMPORT_RE.findall(raw):
            imports[mod] |= {n.strip() for n in names.split(",") if n.strip()}
        ex = set(EXPORT_FN_RE.findall(raw))
        for lst in EXPORT_LIST_RE.findall(raw):
            ex |= {n.strip() for n in lst.split(",") if n.strip()}
        exports[mod] = ex
        defs[mod] = {g for tup in DEF_RE.findall(raw) for g in tup if g} | ex

    violations = []

    # C1 判环（DFS）
    graph = {m: set() for m in exports}
    for m in imports:
        for names, frm in IMPORT_RE.findall((SRC / f"{m}.js").read_text(encoding="utf-8")):
            if frm in graph:
                graph[m].add(frm)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {m: WHITE for m in graph}

    def dfs(u, stack):
        color[u] = GRAY
        stack.append(u)
        for v in graph[u]:
            if color[v] == GRAY:
                violations.append(f"C1 环: {' -> '.join(stack[stack.index(v):] + [v])}")
            elif color[v] == WHITE:
                dfs(v, stack)
        stack.pop()
        color[u] = BLACK

    for m in graph:
        if color[m] == WHITE:
            dfs(m, [])

    # C2 跨模块导出名未 import 检测
    for m in exports:
        body = bodies[m]
        for other, names in exports.items():
            if other == m:
                continue
            for n in names:
                if n in imports[m] or n in defs[m]:
                    continue
                if re.search(rf"(?<![.\w]){re.escape(n)}\s*\(", body):  # 排除 m.foo() 成员调用（动态 import 合法姿势）
                    violations.append(f"C2 {m}.js 调用 {n}()（{other} 导出）未 import")

    if violations:
        print("\n".join(sorted(set(violations))))
        return 1
    print("前端护栏干净：无环 + 无跨模块未 import 调用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
