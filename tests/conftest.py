"""tests/conftest.py — memory 测试共享 fixture。

estate 与真实知识地产格式同构：
lessons.md 条目头 = '## Lx — 标题'，节 = '- **节名**：'；ADR 索引行 = '- [NNN — 标题](./NNN-xxx.md)'。
（原计划放在 test_memory_estate.py 内、跨文件 import 复用；ruff F811 不认该模式，提升到 conftest。）
"""
from pathlib import Path

import pytest


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
