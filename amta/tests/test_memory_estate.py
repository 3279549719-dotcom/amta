"""tests/test_memory_estate.py — estate 解析层的锁定测试。fixture 见 tests/conftest.py。"""
from pathlib import Path

from amta.memory.estate import build_pack, parse_adrs, lesson_sections, parse_lessons, read_lines

HARD_CAP = 10000
FULL_BUDGET = 1536
SLIM_BUDGET = 512


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


def test_pack_full_within_budget_and_has_dictionary_rule(estate: Path):
    pack = build_pack(estate, source="startup")
    assert len(pack) <= FULL_BUDGET
    assert "=== AMTA 记忆包" in pack
    assert "知识字典" in pack
    assert "memory_search" in pack
    # 内容契约（ADR-027）：不采样 lessons/会话摘要
    assert "L2|第二个坑" not in pack
    assert "## 最近摘要" not in pack


def test_pack_slim_smaller_and_drops_state(estate: Path):
    (estate / ".remember" / "now.md").write_text("现在在写记忆机制。\n", encoding="utf-8")
    full = build_pack(estate, source="startup")
    slim = build_pack(estate, source="compact")
    assert "现在在写记忆机制" not in slim and "现在在写记忆机制" not in full  # 会话摘要不再注入
    assert len(slim) <= SLIM_BUDGET


def test_pack_includes_loop_state_summary_when_present(estate: Path):
    estate.joinpath("loop_state.json").write_text(
        '{"mission": "检测调优", "next_action": "调 conf", "updated_at": "2026-09-01T22:00"}',
        encoding="utf-8",
    )
    pack = build_pack(estate, source="startup")
    assert "## 接续状态" in pack
    assert "检测调优" in pack
    assert "调 conf" in pack


def test_pack_hard_cap_on_huge_loop_state(estate: Path):
    # 字典规则固定；超预算只能由巨大的 loop_state 摘要触发
    estate.joinpath("loop_state.json").write_text('{"mission": "' + "x" * 20000 + '"}', encoding="utf-8")
    pack = build_pack(estate, source="startup")
    assert len(pack) <= HARD_CAP
    assert "截断" in pack
