"""audit 卫生检查测试（workspace 空壳 / 重复文件 / 顶层散落）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


class TestWorkspaceHygiene:
    def test_ws_empty_dirs_detected(self, tmp_path):
        from audit import check_workspace_empties
        ws = tmp_path / "workspace"
        (ws / "ws-abc").mkdir(parents=True)
        (ws / "ws-abc" / "artifacts").mkdir()
        (ws / "ws-xyz").mkdir(parents=True)
        (ws / "ws-xyz" / "artifacts").mkdir()
        # 有产物的不报
        (ws / "ws-real" / "artifacts").mkdir(parents=True)
        (ws / "ws-real" / "artifacts" / "page.json").write_text("{}", encoding="utf-8")
        n, paths = check_workspace_empties(ws)
        assert n == 2
        assert all("ws-abc" in p or "ws-xyz" in p for p in paths)
        assert not any("ws-real" in p for p in paths)

    def test_no_workspace_returns_zero(self, tmp_path):
        from audit import check_workspace_empties
        n, paths = check_workspace_empties(tmp_path / "missing")
        assert n == 0 and paths == []


class TestDupDetection:
    def test_duplicate_files_detected(self, tmp_path):
        from audit import find_duplicate_files
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("same content", encoding="utf-8")
        b.write_text("same content", encoding="utf-8")
        (tmp_path / "c.md").write_text("diff content", encoding="utf-8")
        dups = find_duplicate_files(tmp_path)
        assert len(dups) == 1
        assert {p.name for p in dups[0]} == {"a.md", "b.md"}

    def test_skips_git_and_venv(self, tmp_path):
        from audit import find_duplicate_files
        (tmp_path / ".git").mkdir()
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".git" / "x.md").write_text("same", encoding="utf-8")
        (tmp_path / ".venv" / "y.md").write_text("same", encoding="utf-8")
        (tmp_path / "z.md").write_text("same", encoding="utf-8")
        dups = find_duplicate_files(tmp_path)
        assert len(dups) == 0  # git/venv 被跳过，z.md 独一份


class TestTopLevelClutter:
    def test_unexpected_top_files_detected(self, tmp_path):
        from audit import check_top_level_clutter
        (tmp_path / "amta").mkdir()
        (tmp_path / "research").mkdir()
        (tmp_path / "reference").mkdir()
        (tmp_path / "stray.md").write_text("x", encoding="utf-8")
        (tmp_path / "stray.png").write_bytes(b"x")
        bad = check_top_level_clutter(tmp_path)
        assert len(bad) == 2

    def test_allowed_files_ignored(self, tmp_path):
        from audit import check_top_level_clutter
        (tmp_path / "amta").mkdir()
        (tmp_path / ".env").write_text("K=V", encoding="utf-8")
        bad = check_top_level_clutter(tmp_path)
        assert bad == []
