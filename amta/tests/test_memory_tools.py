"""tests/test_memory_tools.py — 检索操作的语义返回锁定测试。estate fixture 见 conftest。"""
from pathlib import Path

from amta.memory.tools import do_grep, do_index, do_recent, do_read


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
