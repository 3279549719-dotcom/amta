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
