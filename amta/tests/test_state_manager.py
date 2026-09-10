"""test_state_manager — StateManager 的 TDD 测试。

StateManager = 对话状态管理（合并 context-bootstrap + finisher）：
- bootstrap(): 对话开始，读取 git + env 状态，输出统一格式的状态摘要
- finish(summary): 对话结束，commit + 生成状态快照

设计原则（Embedded，不是 Chained）：
- 不是"告诉 AI 去跑 git log"，是"调用一个函数就拿到所有状态"
- 状态格式统一，AI 不需要解析多种输出
- 可测试，行为确定
"""
from __future__ import annotations

import subprocess

import pytest

from amta.common.state_manager import StateManager, StateSnapshot


@pytest.fixture
def sm(tmp_path):
    """每个测试用独立的 git 仓库，避免污染真实仓库。"""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)
    # 初始 commit
    (repo / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
    return StateManager(repo_root=repo)


class TestStateSnapshot:
    """StateSnapshot 数据类的测试。"""

    def test_snapshot_has_required_fields(self):
        """状态摘要必须包含固定字段，格式统一。"""
        snap = StateSnapshot(
            git_log="commit abc123 feat: test\n",
            git_diff=" M file.py\n",
            git_status=" M file.py\n",
            env_status="env check OK\n",
            branch="main",
            dirty=True,
        )
        assert snap.git_log
        assert snap.git_diff
        assert snap.git_status
        assert snap.env_status
        assert snap.branch
        assert isinstance(snap.dirty, bool)

    def test_snapshot_to_str_has_sections(self):
        """转字符串时必须有清晰的 section 分隔，AI 容易解析。"""
        snap = StateSnapshot(
            git_log="commit abc123 feat: test\n",
            git_diff=" M file.py\n",
            git_status=" M file.py\n",
            env_status="env check OK\n",
            branch="main",
            dirty=True,
        )
        text = str(snap)
        assert "=== GIT LOG ===" in text
        assert "=== GIT DIFF ===" in text
        assert "=== GIT STATUS ===" in text
        assert "=== ENV ===" in text
        assert "branch: main" in text
        assert "dirty: True" in text


class TestBootstrap:
    """bootstrap() — 对话开始读取状态。"""

    def test_bootstrap_returns_snapshot(self, sm):
        """bootstrap() 返回 StateSnapshot 对象。"""
        snap = sm.bootstrap()
        assert isinstance(snap, StateSnapshot)

    def test_bootstrap_git_log_has_commits(self, sm):
        """git log 包含历史 commit。"""
        snap = sm.bootstrap()
        assert "init" in snap.git_log

    def test_bootstrap_branch_detection(self, sm):
        """能检测当前分支名。"""
        snap = sm.bootstrap()
        assert snap.branch in ("main", "master")

    def test_bootstrap_clean_repo_not_dirty(self, sm):
        """干净的仓库 dirty=False。"""
        snap = sm.bootstrap()
        assert snap.dirty is False

    def test_bootstrap_dirty_repo_detection(self, sm):
        """有未提交改动时 dirty=True。"""
        (sm.repo_root / "newfile.txt").write_text("dirty\n")
        snap = sm.bootstrap()
        assert snap.dirty is True
        assert "newfile.txt" in snap.git_status


class TestFinish:
    """finish(summary) — 对话结束写入状态。"""

    def test_finish_commits_changes(self, sm):
        """finish() 会 git add + git commit。"""
        (sm.repo_root / "feature.py").write_text("print('hello')\n")
        sm.finish("feat: add feature")
        # 验证 commit 存在
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=sm.repo_root, capture_output=True, text=True, check=True,
        )
        assert "feat: add feature" in result.stdout

    def test_finish_empty_summary_raises(self, sm):
        """summary 为空时抛异常，不允许空 commit。"""
        with pytest.raises(ValueError, match="summary"):
            sm.finish("")

    def test_finish_with_whitespace_summary_raises(self, sm):
        """summary 只有空白时也抛异常。"""
        with pytest.raises(ValueError, match="summary"):
            sm.finish("   \n  ")

    def test_finish_no_changes_no_commit(self, sm):
        """没有改动时不 commit（避免空 commit）。"""
        before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=sm.repo_root, capture_output=True, text=True, check=True,
        ).stdout.strip()
        sm.finish("chore: no changes")
        after = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=sm.repo_root, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert before == after  # HEAD 没变
