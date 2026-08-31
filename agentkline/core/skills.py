"""
AgentKline Skills 加载器。

skills/ 目录下每个 .md 为一个 skill，头部 YAML frontmatter 含 name/description，
正文为完整文档。MCP 通过 list_skills / load_skill 按需暴露给 agent
（仿 vibe-trading 的 list_skills/load_skill 模式），让任意接入方学会
"如何编写能在 AgentKline 合法运行的脚本" 等领域知识，避免试错。
"""
import re
from pathlib import Path

# 项目根/skills（与 scripts/ 同级，随仓库发布）
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _parse(md_text: str):
    """拆 frontmatter（name/description）与正文。"""
    m = _FM_RE.match(md_text)
    meta = {}
    body = md_text
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = md_text[m.end():]
    return meta, body


def list_skills() -> list:
    """返回 [{name, description}]，供 agent 发现可用 skill。"""
    if not SKILLS_DIR.exists():
        return []
    out = []
    for f in sorted(SKILLS_DIR.glob("*.md")):
        meta, _ = _parse(f.read_text(encoding="utf-8"))
        out.append({"name": meta.get("name", f.stem),
                    "description": meta.get("description", "")})
    return out


def load_skill(name: str) -> dict:
    """返回 {name, content}；content 为 skill 正文全文。"""
    if not SKILLS_DIR.exists():
        return {"error": "skills dir not found"}
    for f in sorted(SKILLS_DIR.glob("*.md")):
        meta, body = _parse(f.read_text(encoding="utf-8"))
        if meta.get("name", f.stem) == name or f.stem == name:
            return {"name": meta.get("name", f.stem), "content": body}
    return {"error": f"skill '{name}' not found"}
