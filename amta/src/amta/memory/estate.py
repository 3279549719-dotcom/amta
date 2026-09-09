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
ADR_INDEX_LINE = re.compile(r"^- \[(\d{3}) — (.+?)\]\(\./(.+?)\.md\)", re.MULTILINE)

FULL_BUDGET = 1536   # Q7：startup 全量包 ≤1.5KB
SLIM_BUDGET = 512    # Q7：compact 瘦包 ≤0.5KB
HARD_CAP = 10000     # CC hook 输出硬上限（官方文档），超出会被落盘替换

DICTIONARY_FULL = (
    "知识字典：坑库 docs/lessons.md（L1–L45，顶部有书脊目录）+ 决策 docs/decisions/（ADR-001–033，README 有索引）。"
    "遇错/决策前先查（memory_search / memory_read，或 CLI memory_grep / memory_read），别硬扛；"
    "拿不准馆里有什么书时，先读 lessons.md 顶部目录或 decisions/README.md 索引。"
)
DICTIONARY_SLIM = "遇错/决策前先 memory_search 查知识字典"

TRUNCATED_MARK = "\n[记忆包截断：地产超预算 — memory_recent/memory_grep 打捞全量]"


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
        # 1-based 收口：下一标题行（1-based）的前一行；最后一条到文件尾
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
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
            name = str(m.group(1))
            if cur is not None:
                secs[cur] = (secs[cur][0], i - 1)
            cur = name
            secs[name] = (i, entry.end_line)
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


def build_pack(root: Path, source: str = "startup", budget: int | None = None) -> str:
    """构造注入包。优先级（超预算时从后往前丢）：标题行 > loop_state 摘要 > 字典规则。
    budget=None 按 source 取默认（startup 1536 / compact 512）；显式传 budget 供 lint 量地产体量。
    恒 ≤ HARD_CAP；超预算被丢弃的内容附「截断」标记（防地产膨胀静默吞信息）；
    极端情况下超 HARD_CAP 硬截断（CC 官方上限 10K 字符）。
    内容契约（ADR-027）：只装接续状态 + 字典规则，不采样 lessons/会话摘要（字典按需查）。"""
    budget = budget if budget is not None else (SLIM_BUDGET if source == "compact" else FULL_BUDGET)
    slim = source == "compact"
    blocks: list[str] = []
    ls = root / "loop_state.json"
    if ls.exists() and ls.stat().st_size > 2:
        try:
            from amta.memory.loop_state import load as ls_load, summarize as ls_summarize

            summary = ls_summarize(ls_load(root))
            if summary:
                blocks.append("## 接续状态\n" + summary)
        except Exception:  # noqa: BLE001 — 注入纪律：状态损坏降级为无状态，不阻塞
            pass
    blocks.append(DICTIONARY_SLIM if slim else DICTIONARY_FULL)
    header = f"=== AMTA 记忆包 ({source}) ==="
    pack = header
    dropped = False
    for b in blocks:
        if len(pack) + len(b) + 1 <= budget:
            pack = f"{pack}\n{b}"
        else:
            dropped = True  # 单块超预算：整块丢弃，附标记（计划测试 test_pack_hard_cap_on_huge_estate 的语义）
    if dropped:
        pack += TRUNCATED_MARK
    if len(pack) > HARD_CAP:  # 防御：极端情况硬截断
        pack = pack[: HARD_CAP - 60] + "\n[记忆包截断：超 10K 预算 — 跑 memory_status 排查]"
    return pack
