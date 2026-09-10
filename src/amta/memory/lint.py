"""lint — 记忆机制检查引擎（同引擎双入口：memory_lint --strict 门禁 / memory_status agent 自检）。

规则（Q10 定案 + ADR 索引补充）：
  staleness    recent.md >7 天未更新        → FAIL
  dangling     today-*.md 未归档且 >24h      → WARN
  ghost_path   CLAUDE.md 引用的地产路径不存在 → FAIL
  budget       地产体量（未截断全量包）>1536 WARN；实际注入包 >10K FAIL（构造即知，无需起进程）
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

    full = build_pack(root, "startup", budget=HARD_CAP)   # 未截断全量：量地产真实体量
    injected = build_pack(root, "startup")                # 实际注入包（构造保证 ≤10K）
    if len(injected) > HARD_CAP:  # 防御性 FAIL：注入包本身超硬上限（正常构造不可能触发）
        out.append(Finding("FAIL", "budget", f"注入包 {len(injected)} 字符 > {HARD_CAP}"))
    elif len(full) > FULL_BUDGET:
        out.append(Finding("WARN", "budget", f"地产体量（未截断全量包）{len(full)} 字符 > 预算 {FULL_BUDGET}，注入已截断打捞"))

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
