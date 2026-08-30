"""tests/test_memory_lint.py — 五规则的锁定测试（fixture 时间注入，不睡真时钟）。estate fixture 见 conftest。"""
import datetime
import os
import time
from pathlib import Path

from amta.memory.lint import run_checks


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
