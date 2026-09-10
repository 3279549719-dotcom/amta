"""tools — 检索操作核心：grep/read/index/recent。

返回值纪律（Q8/Q2）：语义单元 + 行号指针，绝不返回整文件；
单工具输出有行数上限，衔接下一步用内置 read（路径+行号已给足）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from amta.common.encoding import run_text_or
from amta.memory.estate import (
    Entry,
    estate_root,
    lesson_sections,
    parse_adrs,
    parse_lessons,
    parse_remember,
    read_lines,
)

GREP_MAX_LINES = 20     # 单次命中行数上限（保留给 CLI 层提示用）
READ_MAX_LINES = 80     # 单条目/节输出行数上限
RECENT_MAX_LINES = 30

_SECTION_MARK = re.compile(r"^- \*\*[^*]+\*\*：?")


@dataclass
class Hit:
    entry_id: str
    title: str
    path: Path
    start_line: int
    end_line: int
    hit_line_no: int
    hit_text: str


def _scopes(root: Path, scope: str) -> list[tuple[str, list[Entry]]]:
    pairs: list[tuple[str, list[Entry]]] = [("lessons", parse_lessons(root))]
    if scope in ("decisions", "all"):
        pairs.append(("decisions", parse_adrs(root)))
    if scope in ("remember", "all"):
        pairs.append(("remember", parse_remember(root)))
    if scope == "all" and (root / "research").exists():
        pairs.append(("research", [Entry(f.stem, f.stem, f, 1, 1) for f in sorted((root / "research").glob("*.md"))]))
    return pairs


def _fmt(h: Hit) -> str:
    er = estate_root()
    rel = h.path.relative_to(er) if h.path.is_absolute() and h.path.is_relative_to(er) else h.path
    rng = f"{rel.as_posix()}:{h.start_line}-{h.end_line}" if h.end_line > h.start_line else f"{rel.as_posix()}:{h.hit_line_no}"
    return f"{h.entry_id}|{h.title}|{rng}|{h.hit_text[:80]}"


def do_grep(
    root: Path, query: str, scope: str = "all", limit: int = 10, tokens: list[str] | None = None
) -> list[Hit]:
    """条目级检索。tokens 非空时 = 多词 AND（每词须在条目内任意行出现，跨行也行）；
    否则按单正则（合法正则原样编译，否则转义字面）。命中返回条目级语义单元，各报首个命中行。"""
    pats = [re.compile(re.escape(t)) for t in tokens] if tokens else None
    if pats is None:
        pat = re.compile(query) if _valid_re(query) else re.compile(re.escape(query))
    else:
        pat = None
    hits: list[Hit] = []
    for _name, entries in _scopes(root, scope):
        for e in entries:
            if e.end_line <= e.start_line and e.entry_id == e.title:
                continue  # research 的目录壳条目，正文由行扫描覆盖
            lines = read_lines(e.path)
            if pats is not None:
                entry_lines = lines[e.start_line - 1 : e.end_line]
                if not all(any(p.search(line) for line in entry_lines) for p in pats):
                    continue
                anchor = next((i for i, line in enumerate(entry_lines) if pats[0].search(line)), 0)
                hits.append(
                    Hit(e.entry_id, e.title, e.path, e.start_line, e.end_line, e.start_line + anchor, entry_lines[anchor].strip())
                )
                continue
            assert pat is not None  # 单词路径已绑定（tokens 为空分支）
            for i in range(e.start_line - 1, min(e.end_line, len(lines))):
                if pat.search(lines[i]):
                    hits.append(Hit(e.entry_id, e.title, e.path, e.start_line, e.end_line, i + 1, lines[i].strip()))
                    break  # 每条目只报首个命中：返回是"条目级"语义单元
    return hits[:limit]


def _valid_re(q: str) -> bool:
    try:
        re.compile(q)
        return True
    except re.error:
        return False


def do_read(root: Path, entry: str, section: str | None = None) -> str:
    for e in parse_lessons(root) + parse_adrs(root) + parse_remember(root):
        if e.entry_id == entry:
            lines = read_lines(e.path)
            if section is None:
                body = lines[e.start_line - 1 : min(e.end_line, e.start_line - 1 + READ_MAX_LINES)]
                return f"{e.entry_id} — {e.title} ({e.path.name}:{e.start_line}-{e.end_line})\n" + "\n".join(body)
            secs = lesson_sections(lines, e)
            if section not in secs:
                raise SystemExit(f"[memory_read] 未知节 {section!r}；可选: {sorted(secs)}")
            s, t = secs[section]
            raw = lines[s - 1 : min(t, s - 1 + READ_MAX_LINES)]
            if raw:
                raw[0] = _SECTION_MARK.sub("", raw[0])  # 剥节标记，只留内容
            return "\n".join(raw).strip()
    raise SystemExit(f"[memory_read] 找不到条目 {entry!r}；用 memory_index 看清单")


def do_index(root: Path, type_: str = "all") -> str:
    out: list[str] = []
    if type_ in ("lessons", "all"):
        for e in parse_lessons(root):
            out.append(f"{e.entry_id}|{e.title}|docs/lessons.md")
    if type_ in ("decisions", "all"):
        for e in parse_adrs(root):
            out.append(f"{e.entry_id}|{e.title}|{e.path.relative_to(root).as_posix()}")
    if type_ in ("remember", "all"):
        for e in parse_remember(root):
            out.append(f"{e.entry_id}|{e.path.parent.name}/{e.path.name}|{e.path.relative_to(root).as_posix()}")
    return "\n".join(out)


def do_recent(root: Path) -> str:
    out: list[str] = []
    r = root / ".remember"
    now = r / "now.md"
    if now.exists() and now.stat().st_size > 2:
        out.append("## now.md")
        out += read_lines(now)[: RECENT_MAX_LINES // 3]
    rec = r / "recent.md"
    if rec.exists():
        out.append("## recent.md（头部）")
        out += read_lines(rec)[: RECENT_MAX_LINES // 2]
    dangling = [f.name for f in r.glob("today-*.md") if not f.name.endswith(".done.md")]
    if dangling:
        out.append(f"## 未归档 today: {', '.join(dangling)}")
    g = run_text_or(
        ["git", "log", "-3", "--oneline", "--", "docs", ".remember", "research", "CLAUDE.md"],
        cwd=root, timeout=10,
    )
    if g.strip():
        out.append("## estate 最近提交")
        out += g.strip().splitlines()[:3]
    return "\n".join(out)
