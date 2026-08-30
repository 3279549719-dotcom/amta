# Agent Memory System Implementation Plan（记忆机制四层闭环）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 amta 建"接手 agent 必然带着记忆开工"的四层机制：基线自动加载 + SessionStart hook 注入（startup/compact）+ memory_* 工具族按需打捞 + test/lint 护栏进 fastcheck。

**Architecture:** 只读解析层（src/amta/memory/estate.py）把知识地产解析为结构化条目（L 编号/ADR id/行范围）；检索层（tools.py）在其上实现 grep/read/index/recent 四操作 + 注入包构造；检查层（lint.py）四+一规则同引擎双入口（CLI 门禁 / agent 自检）；注入 CLI 读 stdin JSON 按 source 出全量/瘦包，纯 stdout、恒 exit 0。Claude Code 原生接 hooks；DSH 侧遵守 L11（hook 只走 git hooks）——桥接注入**门控验证后才开**，此前 DSH 靠基线层 + 工具层覆盖。

**Tech Stack:** Python 3.13 stdlib only（re/json/argparse/pathlib；零第三方依赖，过 depguard）。pytest 风格测试（L19：fastcheck 用 pytest 收集）。Windows 优先（L26：验证用全局 Python 3.13 解释器）。

**依据文档:** research/07-agent记忆机制详报.md（一手调研）· grill-me 三轮共识 Q1-Q11 · docs/decisions/024（本计划产出）· L11/ADR-009（hook 约束）· L26/L19（验证环境约束）。

---

## 文件结构（职责边界）

```
src/amta/memory/__init__.py        # 包标记（空）
src/amta/memory/estate.py          # 只读解析层：条目解析/清单/注入包构造（唯一格式化点）
src/amta/memory/tools.py           # 检索操作：grep/read/index/recent 的核心逻辑 + CLI 入口
src/amta/memory/lint.py            # 检查引擎：五规则，输出 Finding 列表（CLI 与 status 共用）
scripts/memory_grep.py             # 薄 CLI：内容检索
scripts/memory_index.py            # 薄 CLI：地产清单
scripts/memory_read.py             # 薄 CLI：条目/节读取
scripts/memory_recent.py           # 薄 CLI：时效状态
scripts/memory_status.py           # 薄 CLI：agent 自检（宽松模式）
scripts/memory_lint.py             # 薄 CLI：CI 门禁（--strict）
scripts/memory_inject.py           # hook：stdin JSON → 注入包 stdout，恒 exit 0
tests/test_memory_estate.py        # 解析层测试（fixture 地产）
tests/test_memory_tools.py         # 检索操作测试
tests/test_memory_lint.py          # 检查引擎测试
tests/test_memory_inject.py        # 注入包预算/降级测试
.claude/settings.json              # CC SessionStart hook 注册（项目级）
CLAUDE.md                          # 改渐进式加载表：任务名枚举 → 问题域启发式；清幽灵路径
scripts/fastcheck.py               # 加 _memory_lint 检查步
docs/decisions/024-agent-memory-mechanism.md   # ADR：四层机制 + L11 门控决策
docs/memory-probe.md               # 冷启动探针协议（audit 用）
```

不做：MCP 壳（Q8）、.remember 入库（Q11）、翻译知识接入（Q3）、向量检索（YAGNI，文件总量 <50 个）。

---

### Task 0: 前置清理与新分支

**Files:** 无新建（git 操作）。

- [ ] **Step 1: 处理当前分支未提交改动**

Run: `git -C "E:\manga translator agent\amta" status --short`
Expected: `M tests/test_context_semantic_transfer.py` + `?? branch-status-report.html`

```bash
git add tests/test_context_semantic_transfer.py
git commit -m "wip: context semantic transfer tests (前置收拢)"
```
`branch-status-report.html` 保持 untracked（一次性产物，不进库不删）。

- [ ] **Step 2: 从当前 HEAD 切新分支**

```bash
git checkout -b feature/agent-memory
```

- [ ] **Step 3: 验证 import 通路（决定后续代码的 import 方式）**

Run: `python -c "import sys; sys.path.insert(0,'src'); import amta; print('ok')"`（在仓库根）
Expected: `ok`。若失败，先在 `pyproject.toml` 补 `[tool.pytest.ini_options] pythonpath = ["src"]` 再继续（后续所有代码假设 `amta` 可导入）。

---

### Task 1: estate 解析层（src/amta/memory/estate.py）

**Files:**
- Create: `src/amta/memory/__init__.py`（空文件）
- Create: `src/amta/memory/estate.py`
- Test: `tests/test_memory_estate.py`

- [ ] **Step 1: 写失败测试（fixture 地产 + 解析断言）**

```python
"""tests/test_memory_estate.py — estate 解析层的锁定测试。fixture 与真实格式同构：
lessons.md 条目头 = '## Lx — 标题'，节 = '- **节名**：'；ADR 索引行 = '- [NNN — 标题](./NNN-xxx.md)'。"""
from pathlib import Path

import pytest

from amta.memory.estate import build_pack, parse_adrs, lesson_sections, parse_lessons, read_lines

HARD_CAP = 10000
FULL_BUDGET = 1536
SLIM_BUDGET = 512


@pytest.fixture
def estate(tmp_path: Path) -> Path:
    d = tmp_path / "docs" / "decisions"
    d.mkdir(parents=True)
    (tmp_path / ".remember").mkdir()
    (tmp_path / "docs" / "lessons.md").write_text(
        "# Lessons\n"
        "\n"
        "## L1 — 首个坑\n"
        "\n"
        "- **Problem**：问题A。\n"
        "- **Root cause**：原因A。\n"
        "- **Durable lesson**：教训A。\n"
        "- **Prevention**：预防A。\n"
        "- **Regression**：暂无。\n"
        "\n"
        "## L2 — 第二个坑\n"
        "\n"
        "- **Problem**：问题B。\n"
        "- **Root cause**：原因B。\n"
        "- **Durable lesson**：教训B。\n"
        "- **Prevention**：预防B。\n"
        "- **Regression**：暂无。\n",
        encoding="utf-8",
    )
    (d / "001-first.md").write_text("# ADR-001 first\n\n决策正文。\n", encoding="utf-8")
    (d / "002-orphan.md").write_text("# ADR-002 orphan\n\n未入索引的决策。\n", encoding="utf-8")
    (d / "README.md").write_text(
        "# ADR\n\n- [001 — 第一个决策](./001-first.md)\n", encoding="utf-8"
    )
    (tmp_path / ".remember" / "recent.md").write_text(
        "# Recent\n\n## 2026-08-30\n今天做了记忆机制。\n", encoding="utf-8"
    )
    return tmp_path


def test_parse_lessons_finds_entries_with_ranges(estate: Path):
    es = parse_lessons(estate)
    assert [e.entry_id for e in es] == ["L1", "L2"]
    assert es[0].title == "首个坑"
    assert es[0].start_line == 3
    assert es[0].end_line == 10  # 到下一条标题前一行为止
    assert es[1].end_line == 17  # 最后一条到文件尾


def test_lesson_sections_exact_ranges(estate: Path):
    es = parse_lessons(estate)
    lines = read_lines(es[0].path)
    secs = lesson_sections(lines, es[0])
    assert secs["Problem"] == (5, 5)
    assert secs["Durable lesson"] == (7, 7)


def test_parse_adrs_uses_index_title_and_flags_orphans(estate: Path):
    adrs = parse_adrs(estate)
    by_id = {e.entry_id: e for e in adrs}
    assert by_id["ADR-001"].title == "第一个决策"
    assert by_id["ADR-002"].title == "002-orphan"  # 索引缺失 → 回退文件名


def test_pack_full_within_budget_and_has_sections(estate: Path):
    pack = build_pack(estate, source="startup")
    assert len(pack) <= FULL_BUDGET
    assert "=== AMTA 记忆包" in pack
    assert "L2|第二个坑" in pack
    assert "memory_grep" in pack


def test_pack_slim_smaller_and_drops_state(estate: Path):
    (estate / ".remember" / "now.md").write_text("现在在写记忆机制。\n", encoding="utf-8")
    full = build_pack(estate, source="startup")
    slim = build_pack(estate, source="compact")
    assert "现在在写记忆机制" not in slim and "现在在写记忆机制" in full
    assert len(slim) <= SLIM_BUDGET


def test_pack_hard_cap_on_huge_estate(estate: Path):
    (estate / ".remember" / "recent.md").write_text("x" * 20000 + "\n", encoding="utf-8")
    pack = build_pack(estate, source="startup")
    assert len(pack) <= HARD_CAP
    assert "截断" in pack
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_memory_estate.py -q --basetemp output/logs/.pytest-basetemp`
Expected: FAIL（`ModuleNotFoundError: amta.memory`）

- [ ] **Step 3: 实现 estate.py**

```python
"""estate — 知识地产的只读解析层。

把 docs/ + .remember/ 的知识文件解析成结构化条目（ID/标题/行范围），
供 memory_* 工具族与注入包共用。本模块不写任何文件。
行号约定：全部 1-based、含端点；条目 end_line = 下一标题行 - 1（最后一条到文件尾）。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

LESSONS_LINE = re.compile(r"^## (L\d+) — (.+?)\s*$")
SECTION_LINE = re.compile(r"^- \*\*(Problem|Root cause|Durable lesson|Prevention|Regression)\*\*")
ADR_INDEX_LINE = re.compile(r"^- \[(\d{3}) — (.+?)\]\(\./(.+?)\.md\)")

FULL_BUDGET = 1536   # Q7：startup 全量包 ≤1.5KB
SLIM_BUDGET = 512    # Q7：compact 瘦包 ≤0.5KB
HARD_CAP = 10000     # CC hook 输出硬上限（官方文档），超出会被落盘替换

HEURISTIC_FULL = (
    "遇到报错/异常/陌生流程 → memory_grep --query <关键词>；"
    "接手任务 → memory_recent；架构决策前 → memory_grep --scope decisions"
)
HEURISTIC_SLIM = "异常先 memory_grep 再动手"


@dataclass
class Entry:
    entry_id: str   # "L19" / "ADR-016" / remember 文件名
    title: str
    path: Path
    start_line: int # 1-based 含标题行
    end_line: int   # 1-based 含末行


def estate_root(root: Path | None = None) -> Path:
    """显式传参 > CLAUDE_PROJECT_DIR（CC hook 环境注入）> cwd。"""
    if root is not None:
        return root
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env) if env else Path.cwd()


def read_lines(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8").splitlines()


def _entries_from_headers(lines: list[str], path: Path, regex: re.Pattern[str], id_join: str = "") -> list[Entry]:
    heads = []
    for i, line in enumerate(lines):
        m = regex.match(line)
        if m:
            heads.append((i, id_join + m.group(1), m.group(2)))
    out = []
    for k, (i, eid, title) in enumerate(heads):
        end = heads[k + 1][0] - 1 if k + 1 < len(heads) else len(lines)
        out.append(Entry(eid, title, path, i + 1, end))
    return out


def parse_lessons(root: Path) -> list[Entry]:
    path = root / "docs" / "lessons.md"
    if not path.exists():
        return []
    return _entries_from_headers(read_lines(path), path, LESSONS_LINE)


def lesson_sections(lines: list[str], entry: Entry) -> dict[str, tuple[int, int]]:
    """条目内五段节的行范围。返回 {节名: (start, end)}，1-based 含端点。"""
    secs: dict[str, tuple[int, int]] = {}
    cur: str | None = None
    for i in range(entry.start_line, entry.end_line + 1):
        m = SECTION_LINE.match(lines[i - 1])
        if m:
            if cur is not None:
                secs[cur] = (secs[cur][0], i - 1)
            cur = m.group(1)
            secs[cur] = (i, entry.end_line)
    return secs


def parse_adrs(root: Path) -> list[Entry]:
    d = root / "docs" / "decisions"
    if not d.exists():
        return []
    index: dict[str, str] = {}
    readme = d / "README.md"
    if readme.exists():
        for m in ADR_INDEX_LINE.finditer(readme.read_text(encoding="utf-8")):
            index[m.group(1)] = m.group(2)
    out = []
    for f in sorted(d.glob("0*.md")):
        num = f.stem.split("-")[0]
        out.append(Entry(f"ADR-{num}", index.get(num, f.stem), f, 1, len(read_lines(f))))
    return out


def parse_remember(root: Path) -> list[Entry]:
    r = root / ".remember"
    if not r.exists():
        return []
    out = []
    for name in ("now.md", "recent.md", "archive.md"):
        f = r / name
        if f.exists():
            out.append(Entry(name, name, f, 1, len(read_lines(f))))
    for f in sorted(r.glob("today-*.md")):
        out.append(Entry(f.name, f.name, f, 1, len(read_lines(f))))
    return out


def build_pack(root: Path, source: str = "startup") -> str:
    """构造注入包。优先级（超预算时从后往前丢）：标题行 > lessons 尾部 > 启发式 > now > recent。
    恒 ≤ HARD_CAP；超 HARD_CAP 截断并附标记（CC 官方上限 10K 字符）。"""
    budget = SLIM_BUDGET if source == "compact" else FULL_BUDGET
    slim = source == "compact"
    lessons = parse_lessons(root)
    blocks: list[str] = []
    if lessons:
        blocks.append("\n".join(f"{e.entry_id}|{e.title}" for e in lessons[-5:]))
    blocks.append(HEURISTIC_SLIM if slim else HEURISTIC_FULL)
    if not slim:
        now = root / ".remember" / "now.md"
        if now.exists() and now.stat().st_size > 2:
            blocks.append("## 上次状态\n" + "\n".join(read_lines(now)[:15]))
        rec = root / ".remember" / "recent.md"
        if rec.exists():
            blocks.append("## 最近摘要 (memory_recent 看全量)\n" + "\n".join(read_lines(rec)[:12]))
    header = f"=== AMTA 记忆包 ({source}) ==="
    pack = header
    for b in blocks:
        if len(pack) + len(b) + 1 <= budget:
            pack = f"{pack}\n{b}"
    if len(pack) > HARD_CAP:  # 防御：预算逻辑兜底失败时硬截断
        pack = pack[: HARD_CAP - 60] + "\n[记忆包截断：超 10K 预算 — 跑 memory_status 排查]"
    return pack
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_memory_estate.py -q --basetemp output/logs/.pytest-basetemp`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/amta/memory tests/test_memory_estate.py
git commit -m "feat(memory): estate 只读解析层 + 注入包构造（TDD）"
```

---

### Task 2: 检索操作核心（src/amta/memory/tools.py）

**Files:**
- Create: `src/amta/memory/tools.py`
- Test: `tests/test_memory_tools.py`

- [ ] **Step 1: 写失败测试**

```python
"""tests/test_memory_tools.py — 检索操作的语义返回锁定测试。"""
from pathlib import Path

import pytest

from amta.memory.tools import do_grep, do_index, do_recent, do_read

from tests.test_memory_estate import estate


def test_grep_returns_entry_unit_not_full_text(estate: Path):
    hits = do_grep(estate, query="原因")
    assert len(hits) == 2
    h = hits[0]
    assert h.entry_id == "L1" and h.title == "首个坑"
    assert h.path.as_posix().endswith("docs/lessons.md")
    assert h.hit_line_no == 6 and "原因A" in h.hit_text


def test_grep_scope_decisions(estate: Path):
    hits = do_grep(estate, query="决策", scope="decisions")
    assert [h.entry_id for h in hits] == ["ADR-001", "ADR-002"]


def test_grep_limit(estate: Path):
    assert len(do_grep(estate, query="原因", limit=1)) == 1


def test_read_whole_entry_and_single_section(estate: Path):
    text = do_read(estate, entry="L1")
    assert "问题A" in text and "教训B" not in text
    sec = do_read(estate, entry="L1", section="Durable lesson")
    assert sec.strip() == "教训A。"


def test_read_adr_entry(estate: Path):
    assert "决策正文" in do_read(estate, entry="ADR-001")


def test_index_lists_all_types_with_id_and_path(estate: Path):
    out = do_index(estate, type_="all")
    assert "L1|首个坑|docs/lessons.md" in out
    assert "ADR-001|第一个决策|docs/decisions/001-first.md" in out
    assert "recent.md|.remember/recent.md" in out
    only_decisions = do_index(estate, type_="decisions")
    assert "ADR-002" in only_decisions and "L1" not in only_decisions


def test_recent_includes_remember_and_git(estate: Path):
    out = do_recent(estate)
    assert "今天做了记忆机制" in out
    assert "recent.md" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_memory_tools.py -q --basetemp output/logs/.pytest-basetemp`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 tools.py**

```python
"""tools — 检索操作核心：grep/read/index/recent。

返回值纪律（Q8/Q2）：语义单元 + 行号指针，绝不返回整文件；
单工具输出有行数上限，衔接下一步用内置 read（路径+行号已给足）。
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from amta.memory.estate import (
    Entry,
    estate_root,
    lesson_sections,
    parse_adrs,
    parse_lessons,
    parse_remember,
    read_lines,
)

GREP_MAX_LINES = 20     # 单次命中行数上限
READ_MAX_LINES = 80     # 单条目/节输出行数上限
RECENT_MAX_LINES = 30


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
    if scope == "all":
        pairs.append(("research", [
            Entry(f.stem, f.stem, f, 1, 1)
            for f in sorted((root / "research").glob("*.md"))
        ]) if (root / "research").exists() else [])
    return pairs


def _fmt(h: Hit) -> str:
    rel = h.path.relative_to(estate_root()) if h.path.is_absolute() else h.path
    rng = f"{rel.as_posix()}:{h.start_line}-{h.end_line}" if h.end_line > h.start_line else f"{rel.as_posix()}:{h.hit_line_no}"
    return f"{h.entry_id}|{h.title}|{rng}|{h.hit_text[:80]}"


def do_grep(root: Path, query: str, scope: str = "all", limit: int = 10) -> list[Hit]:
    pat = re.compile(query) if _valid_re(query) else re.compile(re.escape(query))
    hits: list[Hit] = []
    for _name, entries in _scopes(root, scope):
        for e in entries:
            if e.end_line <= e.start_line and e.entry_id == e.title:
                continue  # research 的目录壳条目，正文由行扫描覆盖
            lines = read_lines(e.path)
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
            body = lines[s - 1 : min(t, s - 1 + READ_MAX_LINES)]
            return f"{e.entry_id}.{section} ({e.path.name}:{s}-{t})\n" + "\n".join(body)
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
    try:
        g = subprocess.run(
            ["git", "log", "-3", "--oneline", "--", "docs", ".remember", "research", "CLAUDE.md"],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
        if g.returncode == 0 and g.stdout.strip():
            out.append("## estate 最近提交")
            out += g.stdout.strip().splitlines()[:3]
    except (OSError, subprocess.TimeoutExpired):
        pass  # git 不可用不影响其余输出
    return "\n".join(out)


import re  # noqa: E402  （置于底部以贴近使用点；ruff 若报错则移至文件头）
```

注意：把 `import re` 移到文件头（顶部 import 区），上面底部 import 是错误示范——实现时直接放顶部。`do_grep` 内 `estate_root()` 用于格式化相对路径；测试中 root 显式传入，`_fmt` 仅被 CLI 层调用，核心函数返回 `Hit` 对象（测试断言字段，不断言 `_fmt` 字符串）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_memory_tools.py -q --basetemp output/logs/.pytest-basetemp`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/amta/memory/tools.py tests/test_memory_tools.py
git commit -m "feat(memory): grep/read/index/recent 检索核心（条目级语义返回）"
```

---

### Task 3: 五个薄 CLI（scripts/memory_*.py）

**Files:**
- Create: `scripts/memory_grep.py`、`scripts/memory_index.py`、`scripts/memory_read.py`、`scripts/memory_recent.py`、`scripts/memory_status.py`（status 在 Task 4 引擎后补全，本任务先建文件骨架——不，避免半成品：本任务只建 grep/index/read/recent 四个，status 归 Task 4）

**Files（修订）:**
- Create: `scripts/memory_grep.py`, `scripts/memory_index.py`, `scripts/memory_read.py`, `scripts/memory_recent.py`

- [ ] **Step 1: 写四个薄 CLI（同构模板，职责只有参数解析 + 调核心 + 打印）**

`scripts/memory_grep.py`：
```python
"""memory_grep — 知识地产内容检索。

用法: python scripts/memory_grep.py --query <关键词|正则> [--scope lessons|decisions|remember|research|all] [--limit N]
返回: 每命中条目一行 `ID|标题|路径:行范围|命中行`（每条目只报首个命中，不给全文）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.memory.estate import estate_root
from amta.memory.tools import _fmt, do_grep


def main() -> int:
    ap = argparse.ArgumentParser(description="知识地产内容检索")
    ap.add_argument("--query", required=True, help="关键词或正则")
    ap.add_argument("--scope", default="all", choices=["lessons", "decisions", "remember", "research", "all"])
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    hits = do_grep(estate_root(), query=a.query, scope=a.scope, limit=a.limit)
    if not hits:
        print(f"[memory_grep] 无命中：{a.query!r}（scope={a.scope}）——换个关键词，或 memory_index 看清单")
        return 0
    for h in hits:
        print(_fmt(h))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`scripts/memory_index.py`：
```python
"""memory_index — 知识地产清单（有什么可查）。

用法: python scripts/memory_index.py [--type lessons|decisions|remember|all]
返回: 每条一行 `ID|标题|路径`。generated-from-reality，永不与地产漂移。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.memory.estate import estate_root
from amta.memory.tools import do_index


def main() -> int:
    ap = argparse.ArgumentParser(description="知识地产清单")
    ap.add_argument("--type", dest="type_", default="all", choices=["lessons", "decisions", "remember", "all"])
    a = ap.parse_args()
    print(do_index(estate_root(), type_=a.type_))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`scripts/memory_read.py`：
```python
"""memory_read — 条目/节聚焦读取。

用法: python scripts/memory_read.py --entry L19 [--section Problem|Root cause|Durable lesson|Prevention|Regression]
      python scripts/memory_read.py --entry ADR-016
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.memory.estate import estate_root
from amta.memory.tools import do_read


def main() -> int:
    ap = argparse.ArgumentParser(description="条目聚焦读取")
    ap.add_argument("--entry", required=True, help="L19 / ADR-016 / remember 文件名")
    ap.add_argument("--section", default=None, help="仅 lessons 支持五段节名")
    a = ap.parse_args()
    print(do_read(estate_root(), entry=a.entry, section=a.section))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`scripts/memory_recent.py`：
```python
"""memory_recent — 时效状态（上次停在哪、最近改了什么）。

用法: python scripts/memory_recent.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.memory.estate import estate_root
from amta.memory.tools import do_recent


def main() -> int:
    print(do_recent(estate_root()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 真仓库冒烟（四条命令，人工核对输出形态）**

Run: `python scripts/memory_index.py --type decisions` → Expected: 23 行 `ADR-0NN|...`
Run: `python scripts/memory_grep.py --query "PermissionError" --scope lessons` → Expected: `L19|pytest Windows 尾部 PermissionError...|docs/lessons.md:NNN-NNN|...`
Run: `python scripts/memory_read.py --entry L19 --section Durable lesson` → Expected: 输出教训正文
Run: `python scripts/memory_recent.py` → Expected: 含 recent.md 头部 + estate 最近提交

- [ ] **Step 3: Commit**

```bash
git add scripts/memory_grep.py scripts/memory_index.py scripts/memory_read.py scripts/memory_recent.py
git commit -m "feat(memory): grep/index/read/recent 四个薄 CLI"
```

---

### Task 4: 检查引擎 + status/lint 双入口

**Files:**
- Create: `src/amta/memory/lint.py`
- Create: `scripts/memory_status.py`、`scripts/memory_lint.py`
- Test: `tests/test_memory_lint.py`

- [ ] **Step 1: 写失败测试（fixture 驱动五规则）**

```python
"""tests/test_memory_lint.py — 五规则的锁定测试（fixture 时间注入，不睡真时钟）。"""
import datetime
import os
import time
from pathlib import Path

import pytest

from amta.memory.lint import run_checks

from tests.test_memory_estate import estate


def _age_file(p: Path, days: float) -> None:
    old = time.time() - days * 86400
    os.utime(p, (old, old))


def test_fresh_estate_all_ok(estate: Path):
    findings = run_checks(estate, today=datetime.date(2026, 8, 30))
    assert not [f for f in findings if f.level == "FAIL"]


def test_staleness_fail_over_7_days(estate: Path):
    _age_file(estate / ".remember" / "recent.md", 9)
    findings = run_checks(estate, today=datetime.date(2026, 8, 30))
    assert any(f.rule == "staleness" and f.level == "FAIL" for f in findings)


def test_dangling_today_warn(estate: Path):
    f = estate / ".remember" / "today-2026-08-28.md"
    f.write_text("## 09:00 | 做了点事\n", encoding="utf-8")
    _age_file(f, 2)
    findings = run_checks(estate, today=datetime.date(2026, 8, 30))
    assert any(f2.rule == "dangling_today" and f2.level == "WARN" for f2 in findings)


def test_ghost_path_fail(estate: Path):
    (estate / "CLAUDE.md").write_text(
        "| 调研报告 | `research/README.md` |\n| 其他 | `docs/lessons.md` |\n", encoding="utf-8"
    )
    findings = run_checks(estate, today=datetime.date(2026, 8, 30))
    ghosts = [f for f in findings if f.rule == "ghost_path" and f.level == "FAIL"]
    assert len(ghosts) == 1 and "research/README.md" in ghosts[0].msg


def test_adr_index_gap_warn(estate: Path):
    findings = run_checks(estate, today=datetime.date(2026, 8, 30))
    assert any(f.rule == "adr_index" and f.level == "WARN" for f in findings)  # 002 未入索引


def test_budget_warn_on_fat_pack(estate: Path):
    (estate / ".remember" / "now.md").write_text("n" * 2000 + "\n", encoding="utf-8")
    findings = run_checks(estate, today=datetime.date(2026, 8, 30))
    assert any(f.rule == "budget" and f.level in ("WARN", "FAIL") for f in findings)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_memory_lint.py -q --basetemp output/logs/.pytest-basetemp`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 lint.py**

```python
"""lint — 记忆机制检查引擎（同引擎双入口：memory_lint --strict 门禁 / memory_status agent 自检）。

规则（Q10 定案 + ADR 索引补充）：
  staleness    recent.md >7 天未更新        → FAIL
  dangling     today-*.md 未归档且 >24h      → WARN
  ghost_path   CLAUDE.md 引用的地产路径不存在 → FAIL
  budget       注入包 >1536 WARN / >10K FAIL（构造即知，无需起进程）
  adr_index    ADR 文件未进 README 索引      → WARN
"""
from __future__ import annotations

import datetime
import re
import time
from dataclasses import dataclass
from pathlib import Path

from amta.memory.estate import (
    ADR_INDEX_LINE,
    FULL_BUDGET,
    HARD_CAP,
    build_pack,
    parse_adrs,
)

GHOST_PATH = re.compile(r"`((?:docs|research|scripts|\.dsh)/[^`]+\.(?:md|py))`")


@dataclass
class Finding:
    level: str  # "OK" | "WARN" | "FAIL"
    rule: str
    msg: str


def run_checks(root: Path, today: datetime.date | None = None) -> list[Finding]:
    out: list[Finding] = []
    today = today or datetime.date.today()
    r = root / ".remember"

    rec = r / "recent.md"
    if rec.exists():
        age = (today - datetime.date.fromtimestamp(rec.stat().st_mtime)).days
        if age > 7:
            out.append(Finding("FAIL", "staleness", f"recent.md 已 {age} 天未更新（>7）"))
        else:
            out.append(Finding("OK", "staleness", f"recent.md {age} 天前更新"))
    else:
        out.append(Finding("WARN", "staleness", ".remember/recent.md 不存在"))

    for f in r.glob("today-*.md"):
        if f.name.endswith(".done.md"):
            continue
        age_h = (time.time() - f.stat().st_mtime) / 3600
        if age_h > 24:
            out.append(Finding("WARN", "dangling_today", f"{f.name} 未归档已 {int(age_h)}h"))

    cm = root / "CLAUDE.md"
    if cm.exists():
        for p in sorted(set(GHOST_PATH.findall(cm.read_text(encoding="utf-8")))):
            if not (root / p).exists():
                out.append(Finding("FAIL", "ghost_path", f"CLAUDE.md 引用不存在的 {p}"))

    pack = build_pack(root, "startup")
    if len(pack) > HARD_CAP:
        out.append(Finding("FAIL", "budget", f"注入包 {len(pack)} 字符 > {HARD_CAP}"))
    elif len(pack) > FULL_BUDGET:
        out.append(Finding("WARN", "budget", f"注入包 {len(pack)} 字符 > 预算 {FULL_BUDGET}"))

    d = root / "docs" / "decisions"
    if (d / "README.md").exists():
        files = {f.stem.split("-")[0] for f in d.glob("0*.md")}
        indexed = {m.group(1) for m in ADR_INDEX_LINE.finditer((d / "README.md").read_text(encoding="utf-8"))}
        missing = sorted(files - indexed)
        if missing:
            out.append(Finding("WARN", "adr_index", f"ADR 未入 README 索引: {', '.join(missing)}"))

    if parse_adrs(root) and not any(f.rule == "adr_index" for f in out):
        out.append(Finding("OK", "adr_index", "ADR 索引覆盖完整"))
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_memory_lint.py -q --basetemp output/logs/.pytest-basetemp`
Expected: `6 passed`

- [ ] **Step 5: 两个 CLI**

`scripts/memory_lint.py`（CI 门禁）：
```python
"""memory_lint — 记忆机制门禁（--strict：任一 FAIL 退出码 1，fastcheck 用）。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.memory.estate import estate_root
from amta.memory.lint import run_checks


def main() -> int:
    ap = argparse.ArgumentParser(description="记忆机制检查（CI 门禁）")
    ap.add_argument("--strict", action="store_true", help="FAIL → 退出码 1")
    a = ap.parse_args()
    findings = run_checks(estate_root())
    for f in findings:
        print(f"[{f.level}] {f.rule}: {f.msg}")
    fails = [f for f in findings if f.level == "FAIL"]
    if a.strict and fails:
        print(f"[memory_lint] strict: {len(fails)} FAIL")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`scripts/memory_status.py`（agent 自检，宽松）：
```python
"""memory_status — 记忆活性自检（与 memory_lint 同引擎；FAIL 不影响退出码，给 agent 看）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.memory.estate import estate_root
from amta.memory.lint import run_checks


def main() -> int:
    findings = run_checks(estate_root())
    for f in findings:
        print(f"[{f.level}] {f.rule}: {f.msg}")
    n_fail = sum(1 for f in findings if f.level == "FAIL")
    print(f"[memory_status] {n_fail} FAIL / {sum(1 for f in findings if f.level == 'WARN')} WARN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: 真仓库冒烟——预期红（幽灵路径尚未修）**

Run: `python scripts/memory_lint.py --strict`
Expected: 退出码 1，含 `ghost_path: CLAUDE.md 引用不存在的 research/...`（这正是它存在的意义；Task 7 修完转绿）

- [ ] **Step 7: Commit**

```bash
git add src/amta/memory/lint.py scripts/memory_status.py scripts/memory_lint.py tests/test_memory_lint.py
git commit -m "feat(memory): 五规则检查引擎 + status/lint 双入口（真仓库幽灵路径红 = 预期）"
```

---

### Task 5: 注入 hook（scripts/memory_inject.py + .claude/settings.json）

**Files:**
- Create: `scripts/memory_inject.py`
- Create: `.claude/settings.json`
- Test: `tests/test_memory_inject.py`

- [ ] **Step 1: 写失败测试（stdin 三态 + 预算）**

```python
"""tests/test_memory_inject.py — hook 三态：正常/坏 JSON/空地产 + 瘦包分支。"""
import json
import subprocess
import sys
from pathlib import Path

from tests.test_memory_estate import estate

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "memory_inject.py"


def _run(estate: Path, stdin_text: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=stdin_text, capture_output=True, text=True, timeout=30,
        cwd=str(estate), env={"CLAUDE_PROJECT_DIR": str(estate), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""), "PATH": __import__("os").environ.get("PATH", "")},
    )


def test_startup_full_pack(estate: Path):
    r = _run(estate, json.dumps({"session_id": "s1", "source": "startup"}))
    assert r.returncode == 0
    assert "=== AMTA 记忆包 (startup)" in r.stdout
    assert len(r.stdout) <= 1536 + 1  # +1 尾换行


def test_compact_slim_pack(estate: Path):
    r = _run(estate, json.dumps({"session_id": "s1", "source": "compact"}))
    assert r.returncode == 0
    assert "(compact)" in r.stdout
    assert len(r.stdout) <= 512 + 1


def test_bad_json_still_exit0_with_pack(estate: Path):
    r = _run(estate, "not json at all")
    assert r.returncode == 0
    assert "=== AMTA 记忆包" in r.stdout


def test_empty_stdin_falls_back(estate: Path):
    r = _run(estate, "")
    assert r.returncode == 0
    assert "=== AMTA 记忆包" in r.stdout
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_memory_inject.py -q --basetemp output/logs/.pytest-basetemp`
Expected: FAIL（脚本不存在）

- [ ] **Step 3: 实现 memory_inject.py**

```python
"""memory_inject — SessionStart hook：把记忆包打到 stdout（CC 原生注入为上下文）。

协议（code.claude.com/docs/en/hooks）：SessionStart 的 plain stdout 直接入上下文；
stdin 是事件 JSON（含 source: startup/resume/clear/compact/fork）。
纪律：① 恒 exit 0（绝不阻塞会话启动）；② 必须消费完 stdin；
     ③ source=compact 出瘦包（≤0.5KB），其余全量包（≤1.5KB）；④ 空地产也要有合法输出。
手动测试：echo '{"source":"startup"}' | python scripts/memory_inject.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.memory.estate import build_pack, estate_root


def main() -> int:
    raw = ""
    if not sys.stdin.isatty():
        raw = sys.stdin.read()
    source = "startup"
    try:
        payload = json.loads(raw) if raw.strip() else {}
        source = payload.get("source", "startup") or "startup"
    except (json.JSONDecodeError, ValueError):
        source = "startup"  # 坏 JSON 不升级为故障：给默认包
    if source not in ("startup", "resume", "clear", "compact", "fork"):
        source = "startup"
    print(build_pack(estate_root(), source=source))
    return 0  # hook 纪律：任何情况下不阻塞会话


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_memory_inject.py -q --basetemp output/logs/.pytest-basetemp`
Expected: `4 passed`

- [ ] **Step 5: 注册 hook（.claude/settings.json——目录现为空，直接新建）**

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          { "type": "command", "command": "python scripts/memory_inject.py" }
        ]
      }
    ]
  }
}
```

不配 matcher（全部 source 都跑，脚本按 source 分支全量/瘦包）。**L11 约束**：此文件只影响 Claude Code；DSH 明确不解释 `.claude/settings.json`（L11），不在本任务给 DSH 接桥。

- [ ] **Step 6: 真会话探针（人工，两步）**

1. Run: `echo '{"source":"compact"}' | python scripts/memory_inject.py` → Expected: `(compact)` 包，≤512 字符
2. 在仓库根开一个新的 Claude Code 会话，看首条 system-reminder/上下文是否出现 `=== AMTA 记忆包 (startup)`；再跑 `/compact` 后确认出现 `(compact)` 包。任一失败 → 查 `python scripts/memory_inject.py` 手动输出与 settings.json 语法，修完再过本步。

- [ ] **Step 7: Commit**

```bash
git add scripts/memory_inject.py .claude/settings.json tests/test_memory_inject.py
git commit -m "feat(memory): SessionStart 注入 hook（startup/compact 双包，恒 exit 0）"
```

---

### Task 6: CLAUDE.md 重写（幽灵路径清零 + 问题域启发式表）

**Files:**
- Modify: `CLAUDE.md`（渐进式加载表整节替换；其余节不动）

- [ ] **Step 1: 替换「渐进式加载」节为下表（原任务名枚举行删除，research/ 幽灵行清零）**

```markdown
## 渐进式加载（问题域启发式：遇到 X → 先做 Y）

> 记忆读取三通道：hook 注入（自动）· memory_* 工具（按需）· 下表（启发式提示）。完整清单 `python scripts/memory_index.py`。

| 症状 / 场景 | 先做 |
|---|---|
| 任何报错 / 测试失败 / 行为异常 | `python scripts/memory_grep.py --query "<关键词>"`（先搜 lessons，别重踩） |
| 接手任务 / 不知道停在哪 | `python scripts/memory_recent.py` |
| 架构 / 选型决策前 | `python scripts/memory_grep.py --scope decisions --query "<主题>"` |
| 改 prompt 模板 / 翻译护栏前 | `python scripts/memory_read.py --entry L24`（L21-L23 同查） |
| 写评测 / 基准数字前 | `python scripts/memory_grep.py --query "评测 坐标 GT" --scope lessons` |
| 新增技能 / 改 SKILL.md | `python scripts/memory_read.py --entry L11` |
| 可复用经验沉淀 / 任务收尾 | `.dsh/skills/cycle-close/SKILL.md`（/finish 流程） |
| 跑 Benchmark A/B/C | `.dsh/skills/benchmark/SKILL.md` |
| 驱动 koharu（接口/mask/修复循环） | `.dsh/skills/koharu-drive/SKILL.md` |
| 记忆可疑 / 机制自检 | `python scripts/memory_status.py` |
| 记忆机制设计依据 | `research/07-agent记忆机制详报.md` + `docs/decisions/024-agent-memory-mechanism.md` |
```

同时删除原文档中所有指向 `research/README.md`、`research/01-…`、`research/02-…`、`research/03-…` 的行（幽灵路径）；`docs/README.md`、`docs/lessons.md`、`docs/decisions/README.md` 三行保留（真实存在，lint 会校验）。全文行数目标 <120 行：若超，把「关键坑速查」里已被 lessons 覆盖的行再压缩。

- [ ] **Step 2: 验证 lint 转绿（真仓库）**

Run: `python scripts/memory_lint.py --strict`
Expected: 退出码 0，无 `ghost_path` FAIL（staleness/adr_index 若 WARN 属真实现状，strict 不拦 WARN）

- [ ] **Step 3: 行数门禁**

Run: `(Get-Content CLAUDE.md | Measure-Object -Line).Lines`
Expected: `< 120`

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): 渐进式加载表改问题域启发式 + 清幽灵路径（lint 转绿）"
```

---

### Task 7: fastcheck 接线（护栏进机械层）

**Files:**
- Modify: `scripts/fastcheck.py`（main() 与检查函数区）

- [ ] **Step 1: 加检查函数（放在 `_depguard()` 之后）**

```python
def _memory_lint() -> int:
    """记忆机制活性门（ADR-024）：staleness/幽灵路径/预算。strict：FAIL → 1。"""
    return _run([sys.executable, str(ROOT / "scripts" / "memory_lint.py"), "--strict"], "memory lint")
```

- [ ] **Step 2: main() 里接线（fails 列表同步加项）**

```python
def main() -> int:
    c = _compile()
    lint_rc = _lint()
    t = _typecheck()
    u = _test()
    d = _depguard()
    m = _memory_lint()
    fails = [name for name, rc in (("compile", c), ("lint", lint_rc), ("typecheck", t), ("unit tests", u), ("depguard", d), ("memory lint", m)) if rc]
    if fails:
        print(f"== [fastcheck] FAIL: {', '.join(fails)} ==")
        return 1
    print("== [fastcheck] ALL PASS ==")
    return 0
```

- [ ] **Step 3: 跑全量 fastcheck（用 Python 3.13 全局解释器，L26）**

Run: `npm run fastcheck`
Expected: `== [fastcheck] ALL PASS ==`（23 个既有测试 + 本计划新增 23 个 memory 测试全绿）

- [ ] **Step 4: Commit**

```bash
git add scripts/fastcheck.py
git commit -m "feat(fastcheck): memory lint 并入机械护栏层（ADR-024）"
```

---

### Task 8: ADR-024 + 冷启动探针协议

**Files:**
- Create: `docs/decisions/024-agent-memory-mechanism.md`
- Create: `docs/memory-probe.md`
- Modify: `docs/decisions/README.md`（索引补 024 —— 顺带补 022/023，消 adr_index WARN）

- [ ] **Step 1: 写 ADR-024（内容如下）**

```markdown
# 024 — Agent 记忆机制：四层闭环（注入 + 打捞 + 护栏）

日期：2026-08-30　状态：已采纳

## 决策
1. 读取端机械化四层：基线（CLAUDE.md/AGENTS.md 自动加载 + 问题域启发式表）→ 推送（SessionStart hook 注入记忆包，startup ≤1.5KB / compact ≤0.5KB）→ 拉取（memory_grep/index/read/recent/status 五工具，条目级语义返回）→ 护栏（pytest 锁 hook + memory_lint 五规则进 fastcheck + 冷启动探针挂 audit）。
2. 写路径沿用 claude-remember 插件（.remember/）+ cycle-close 晋升管线，不重造。
3. **DSH 侧注入遵守 L11**：不接 CC hook 桥（进程级泄漏风险）；DSH 会话靠基线层（CLAUDE.md/AGENTS.md 原生注入）+ 工具层（脚本通用）覆盖。何时开桥：等 DSH hooks-claude-code 桥支持项目级 SessionStart + additionalContext 且无跨项目泄漏后，单独验证再开（门控，不默认）。
4. 工具族零第三方依赖（过 depguard）；不建 MCP 壳（脚本对 CC/DSH/Codex 通用）；.remember 维持 gitignore（Q11）。

## 理由
- 实测病根：写入自动化但读取零机械化——.remember 只注入自身文件，lessons/ADR/progress 从未注入；CLAUDE.md 加载表按任务名枚举对不上踩坑场景；research/ 幽灵路径证明索引会腐坏。
- compact 重注入是"长会话遗忘"的机制性解药（压缩 = 记忆丢失点 = 官方重注入钩子）。
- 一次性调研证据：research/07-agent记忆机制详报.md（CC hooks 官方协议 / claude-mem / MCP memory server / claude-remember 实测）。
```

- [ ] **Step 2: 写探针协议 docs/memory-probe.md**

```markdown
# 冷启动探针（记忆活性体检，audit 期执行）

## 方法
在仓库根新开一个 Claude Code 会话（不口头提醒任何背景），依次问三题，核对回答是否引用正确来源。

| # | 问题 | PASS 标准 |
|---|---|---|
| 1 | "这个项目上次做到哪了？接下来该干嘛？" | 回答含 recent.md/now.md 的具体内容（如 context-semantic-transfer 状态） |
| 2 | "pytest 全 PASS 但退出码 1，怎么回事？" | 引用 L19（teardown 噪音 / 看 N passed 汇总行） |
| 3 | "为什么 koharu 的 paddle OCR 引擎不能用？" | 引用 L9 / ADR-008（llama.cpp b8935 MTMD 初始化失败，走独立 llama-server） |

## 判定
- 3/3 PASS = 记忆机制有效；≤1 PASS = 失效，先跑 `python scripts/memory_status.py` 排查注入与地产健康。
- 探针结果记入当次 audit 报告（docs/decisions/022 的 audit probe 流程追加本节）。
```

- [ ] **Step 3: decisions/README.md 索引补三行（022/023/024，消 adr_index WARN）**

在索引列表末尾追加：
```markdown
- [022 — 审计探针结论（audit probe）](./022-audit-probe-conclusion.md)
- [023 — front3 重构](./023-front3-reconstruction.md)
- [024 — Agent 记忆机制：四层闭环（注入 + 打捞 + 护栏）](./024-agent-memory-mechanism.md)
```

- [ ] **Step 4: 验证**

Run: `python scripts/memory_lint.py --strict`
Expected: 退出码 0 且输出含 `[OK] adr_index: ADR 索引覆盖完整`
Run: `python scripts/memory_index.py --type decisions` → Expected: 含 `ADR-024|Agent 记忆机制：四层闭环（注入 + 打捞 + 护栏）`

- [ ] **Step 5: Commit**

```bash
git add docs/decisions/024-agent-memory-mechanism.md docs/decisions/README.md docs/memory-probe.md
git commit -m "docs(memory): ADR-024 定案 + 冷启动探针协议 + ADR 索引补全"
```

---

### Task 9: 收尾验证（verification-before-completion）

- [ ] **Step 1: 全量新鲜验证（L25：记录 HEAD）**

```bash
git status --short   # 必须干净（或只有已提交内容）
git log -1 --format=%H   # 记录验证基线 commit
npm run fastcheck      # Expected: ALL PASS
```

- [ ] **Step 2: 冷启动探针首跑（docs/memory-probe.md 三题）**

Expected: ≥2/3 PASS（3/3 为达标线；不足则回 Task 5/6 排查注入与启发式表）

- [ ] **Step 3: 图解资产刷新**

`research/07-agent记忆机制-图解.html` 与 `research/assets/07-memory-architecture.svg` 的拉取层 chips 更新为五工具（memory_grep/index/read/recent/status），SVG 重截图 PNG。属文档收尾，不阻塞其他任务。

- [ ] **Step 4: Commit + 收尾**

```bash
git add -A
git commit -m "docs(memory): 图解资产对齐五工具族（收尾）"
```
然后走 `.dsh/skills/cycle-close`（/finish）：知识晋升（本机制实施中的新坑写 lessons L32+）、progress.md 更新、Finish Report。

---

## Self-Review（已执行）

1. **Spec 覆盖**：Q4 分支（Task 0）✓ Q7 注入包（Task 1 build_pack + Task 5）✓ Q8 五工具（Task 1-4）✓ Q9 启发式表+幽灵路径（Task 6）✓ Q10 测试护栏（Task 1/2/4/5 测试 + Task 7 fastcheck）✓ Q11 不动 .remember ✓ L11 门控（Task 5 Step 5 + ADR-024 #3）✓
2. **占位扫描**：无 TBD/TODO；所有代码步含完整代码；探针/冒烟步骤含期望输出。
3. **类型一致性**：`Entry(start_line,end_line)` 全文一致；`do_*` 返回类型（Hit list / str）与 CLI 打印层一致；`run_checks(root, today)` 签名在测试与实现一致。
