"""lint — 记忆机制检查引擎（同引擎双入口：memory_lint --strict 门禁 / memory_status agent 自检）。

规则（Q10 定案 + ADR 索引补充）：
  staleness    recent.md >7 天未更新        → FAIL
  dangling     today-*.md 未归档且 >24h      → WARN
  ghost_path   CLAUDE.md 引用的地产路径不存在 → FAIL
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
    parse_adrs,
)

GHOST_PATH = re.compile(r"`((?:docs|research|scripts|\.dsh)/[^`]+\.(?:md|py))`")

#: 「这一行在陈述历史 / 宣告删除，不是在发指令」的标记词。
#:
#: ## 为什么需要它（2026-09-12 实测）
#:
#: ghost_path 原本对**整个 CLAUDE.md 做全文件正则**，没有行概念。于是这样一句
#: 「CC 方言的 hook 层已整体移除（`.claude/settings.json`、`scripts/hook_pretooluse.py` …）」
#: 会被当成"引用了不存在的脚本"而报 FAIL——**陈述历史被误判成发指令**。
#:
#: 同类判断在 `tests/test_reference_integrity.py` 的 S2（tests 里的引用）与
#: S4（操作文档里的引用）也要用。故以此处为**单一事实源**，测试侧 import 它，
#: 不再各写一份——否则又会多出一处"要同步的漂移"。
DELETION_MARKERS: tuple[str, ...] = (
    "已删", "删除", "删掉", "移除", "不存在", "替代", "废弃", "墓碑",
    "legacy", "deprecated", "不要用", "曾经", "不再", "moved", "removed",
    "gone", "tombstone",
)


def is_historical_note(line: str) -> bool:
    """该行是否在陈述「某物已不存在 / 已被替代」，而非在发指令。"""
    return any(mark in line for mark in DELETION_MARKERS)


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
        # 逐行判定，并放行「陈述历史」的行——全文件正则会把"宣告删除"误判成"引用"。
        for line in cm.read_text(encoding="utf-8").splitlines():
            if is_historical_note(line):
                continue
            for p in sorted(set(GHOST_PATH.findall(line))):
                if not (root / p).exists():
                    out.append(Finding("FAIL", "ghost_path", f"CLAUDE.md 引用不存在的 {p}"))

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
