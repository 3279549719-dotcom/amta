"""test_state_finish_gate — 对话结束的强制质检门（2026-09-10 事故驱动）。

事故：全量 pytest 红了约两天无人察觉。原因不是"没有质检"，
而是唯一的 commit 拦截层（pre-commit）只跑 `fastcheck --quick`（**跳过 pytest**），
而交接文档把那次 `QUICK PASS` 记成了"关卡通过"——**半扇门签发了假的通过**。

修法刻意**不是**再造一个 doctor 工具（那只会变成第三层各跑一段的护栏），
而是把完整质检钉在**已经必须经过的那个收口点**上：`state.py finish`。
所以这里针对 `finish_verified` 的行为写测试，gate 可注入 → 不需要真的跑 107 秒。
"""
from __future__ import annotations

import subprocess

import pytest

from amta.common.encoding import run_text
from amta.common.state_manager import (
    GitCommandFailed,
    QualityGateFailed,
    StateManager,
    finish_verified,
)


def _git(repo, *args: str) -> str:
    """跑 git 并正确解码。

    注意：这里**必须**用 run_text，不能图省事写 `subprocess.run(text=True)`——
    那会按宿主 locale(cp936) 解码中文 commit message，断言随即变乱码。
    本文件第一版就是这么写的，三条测试因此假红（正是 src 里刚修的同一个 bug）。
    """
    return run_text(["git", *args], cwd=repo).stdout


@pytest.fixture
def repo(tmp_path):
    """一个干净的 git 仓库（一个提交）。"""
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init"], cwd=r, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=r, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=r, capture_output=True, check=True)
    (r / "a.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=r, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=r, capture_output=True, check=True)
    return r


def _head(repo) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


def _gate_passes() -> int:
    return 0


def _gate_fails() -> int:
    return 1


class TestFinishVerified:
    """gate 红 → 拒绝提交；gate 绿 → 提交。"""

    def test_red_gate_refuses_to_commit(self, repo):
        """质检没过就绝不落盘——这是本门存在的全部理由。"""
        (repo / "new.txt").write_text("dirty\n", encoding="utf-8")
        before = _head(repo)
        with pytest.raises(QualityGateFailed):
            finish_verified("feat: 不该被提交", gate=_gate_fails, repo_root=repo)
        assert _head(repo) == before, "质检红了却仍然产生了提交"

    def test_red_gate_leaves_worktree_dirty(self, repo):
        """拒绝提交后改动必须原样留在工作区（不能顺手 git add 到一半）。"""
        (repo / "new.txt").write_text("dirty\n", encoding="utf-8")
        with pytest.raises(QualityGateFailed):
            finish_verified("feat: x", gate=_gate_fails, repo_root=repo)
        assert "new.txt" in _git(repo, "status", "--short")

    def test_green_gate_commits(self, repo):
        """质检通过则正常落盘。"""
        (repo / "new.txt").write_text("dirty\n", encoding="utf-8")
        finish_verified("feat: 落盘", gate=_gate_passes, repo_root=repo)
        assert "feat: 落盘" in _git(repo, "log", "--oneline", "-1")

    def test_gate_result_is_reported(self, repo):
        """gate 的退出码要能带出来（便于 CLI 打印到底哪一步红）。"""
        (repo / "new.txt").write_text("dirty\n", encoding="utf-8")
        with pytest.raises(QualityGateFailed) as exc:
            finish_verified("feat: x", gate=_gate_fails, repo_root=repo)
        assert exc.value.returncode == 1


class TestNoWorkNoGate:
    """没有改动时：不跑质检、不提交——别为无事发生付 107 秒。"""

    def test_clean_tree_skips_gate_entirely(self, repo):
        called = []

        def gate() -> int:
            called.append(True)
            return 0

        finish_verified("chore: 无改动", gate=gate, repo_root=repo)
        assert called == [], "工作区干净却仍然跑了质检"

    def test_clean_tree_creates_no_commit(self, repo):
        before = _head(repo)
        finish_verified("chore: 无改动", gate=_gate_passes, repo_root=repo)
        assert _head(repo) == before


class TestSkipCheck:
    """--skip-check 是逃生门：显式绕过质检。"""

    def test_skip_check_commits_even_when_gate_would_fail(self, repo):
        (repo / "new.txt").write_text("dirty\n", encoding="utf-8")
        finish_verified("hotfix: 紧急落盘", gate=_gate_fails, repo_root=repo, skip_check=True)
        assert "hotfix: 紧急落盘" in _git(repo, "log", "--oneline", "-1")

    def test_skip_check_does_not_run_the_gate(self, repo):
        called = []

        def gate() -> int:
            called.append(True)
            return 1

        (repo / "new.txt").write_text("dirty\n", encoding="utf-8")
        finish_verified("hotfix: x", gate=gate, repo_root=repo, skip_check=True)
        assert called == []


class TestEmptySummaryStillRejected:
    """空 summary 的既有契约不能被这道门弄丢。"""

    def test_empty_summary_raises_before_gate(self, repo):
        (repo / "new.txt").write_text("dirty\n", encoding="utf-8")
        called = []

        def gate() -> int:
            called.append(True)
            return 0

        with pytest.raises(ValueError, match="summary"):
            finish_verified("   ", gate=gate, repo_root=repo)
        assert called == [], "summary 都非法了，不该先跑质检"


class TestRealGateShape:
    """真实 gate 的形状（不跑完整质检，只验证它不是空壳）。"""

    def test_default_gate_points_at_fastcheck(self):
        from amta.common.state_manager import quality_gate_command
        cmd = quality_gate_command()
        assert any("fastcheck" in part for part in cmd)

    def test_state_manager_still_has_plain_finish(self, repo):
        """不改变原有 finish 契约（库层机制不变，门在收口层）。"""
        (repo / "new.txt").write_text("dirty\n", encoding="utf-8")
        StateManager(repo_root=repo).finish("feat: 裸 finish")
        assert "feat: 裸 finish" in _git(repo, "log", "--oneline", "-1")


class TestWriteFailureIsNotSilent:
    """写操作失败必须炸出来——2026-09-17 实测：唯一收尾入口假报 OK。

    当时的真实路径：`git commit` 触发 pre-commit hook（hook 自己再跑一遍
    `fastcheck --quick`，pyright 冷启动常超 10s）→ 超过 `_run_git` 的
    `timeout=10` → `run_text_or` 按设计把超时吞成空串 → `finish_verified`
    若无其事返回 → CLI 打印 "finish OK"，**而提交根本没落地**，改动静静
    躺在暂存区。

    根因不是超时本身，而是**只读探针的降级助手被复用到了写路径上**：
    「读不到就返回空串」对状态查询是对的，对落盘是灾难。下面用「commit
    非零退出」复现同一个失败形状（超时与非零退出在旧代码里都走同一条
    静默返回路径）。
    """

    def _break_commits(self, repo) -> None:
        """让 `git commit` 确定性地失败：签名程序不存在。"""
        _git(repo, "config", "commit.gpgsign", "true")
        _git(repo, "config", "gpg.program", "/nonexistent-gpg-binary")

    def test_commit_failure_raises_instead_of_reporting_success(self, repo):
        self._break_commits(repo)
        (repo / "a.txt").write_text("changed\n", encoding="utf-8")
        before = _head(repo)

        with pytest.raises(GitCommandFailed):
            finish_verified("probe: 落盘失败", gate=_gate_passes, repo_root=repo)

        assert _head(repo) == before, "提交没落地，HEAD 不该动"
        assert _git(repo, "status", "--short").strip(), "改动应原样留在工作区"

    def test_write_path_actually_uses_strict_variant(self, repo):
        """直接锁住机制：写方法失败必须抛，读方法失败必须降级。"""
        self._break_commits(repo)
        (repo / "a.txt").write_text("changed\n", encoding="utf-8")
        m = StateManager(repo_root=repo)

        with pytest.raises(GitCommandFailed):
            m._run_git_write("commit", "-m", "x")

    def test_read_probes_still_degrade_silently(self, repo):
        """修复不得误伤读取路径：探针失败仍返回空串，不让 CLI 崩。"""
        m = StateManager(repo_root=repo)
        assert m._run_git("log", "--definitely-not-a-real-flag") == ""
