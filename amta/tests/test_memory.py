"""memory.py 的机械测试：索引解析 / 检索命中 / read 分节 / add 写回。

零依赖（仅标准库）。运行:
  PYTHONPATH=src python -m unittest tests.test_memory -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from amta import memory

ROOT = Path(__file__).resolve().parents[1]

SKELETON = """# INDEX — 测试索引

| ID | 触发条件 | 路径 | 一句话价值 |
|---|---|---|---|
| D-001 | 触发甲 | docs/decisions/001-x.md | 价值甲 |
| L-001 | 触发乙 | docs/lessons.md#L1 | 价值乙 |
"""


class TestParseIndex(unittest.TestCase):
    def test_real_index_has_decisions_and_lessons(self) -> None:
        rows = memory.parse_index(ROOT / "docs" / "INDEX.md")
        ids = [r["id"] for r in rows]
        self.assertIn("D-014", ids)
        self.assertIn("L-001", ids)
        self.assertGreaterEqual(len(rows), 30)

    def test_header_and_separator_not_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            idx = Path(td) / "INDEX.md"
            idx.write_text(SKELETON, encoding="utf-8")
            rows = memory.parse_index(idx)
            self.assertEqual([r["id"] for r in rows], ["D-001", "L-001"])


class TestSearch(unittest.TestCase):
    def test_index_hit_ranking(self) -> None:
        out = memory.search("翻译工位 架构", root=ROOT)
        self.assertTrue(out["index_hits"])
        self.assertEqual(out["index_hits"][0]["id"], "D-014")

    def test_fulltext_hit_lessons(self) -> None:
        out = memory.search("坐标", root=ROOT)
        files = {h["file"] for h in out["fulltext_hits"]}
        self.assertIn("docs/lessons.md", files)

    def test_empty_query_returns_empty(self) -> None:
        out = memory.search("   ", root=ROOT)
        self.assertEqual(out["index_hits"], [])
        self.assertEqual(out["fulltext_hits"], [])


class TestRead(unittest.TestCase):
    def test_read_lesson_section(self) -> None:
        text = memory.read("L-007", root=ROOT)
        self.assertTrue(text.startswith("== L-007"))
        self.assertIn("ctd_seg", text)

    def test_read_unknown_id(self) -> None:
        self.assertIn("[miss]", memory.read("Z-999", root=ROOT))

    def test_read_missing_file_reports(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            idx = Path(td) / "INDEX.md"
            idx.write_text(
                SKELETON.replace("docs/decisions/001-x.md", "docs/nope.md"),
                encoding="utf-8",
            )
            self.assertIn("[miss]", memory.read("D-001", index_path=idx, root=Path(td)))


class TestAdd(unittest.TestCase):
    def test_add_appends_row_then_skips_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            idx = Path(td) / "INDEX.md"
            idx.write_text(SKELETON, encoding="utf-8")
            out = memory.add(
                "L-015",
                "做拟声词翻译时",
                "docs/lessons.md#L15",
                "拟声词经验",
                index_path=idx,
            )
            self.assertIn("[added]", out)
            ids = [r["id"] for r in memory.parse_index(idx)]
            self.assertEqual(ids, ["D-001", "L-001", "L-015"])
            out2 = memory.add(
                "L-015", "重复", "docs/lessons.md#L15", "重复", index_path=idx
            )
            self.assertIn("[skip]", out2)


if __name__ == "__main__":
    unittest.main()
