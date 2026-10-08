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

    def test_injected_gate_is_actually_called(self, repo):
        """注入的 gate 必须被调用——不能无视它去跑真 fastcheck。

        回归测试（2026-10-08）：finish_verified 接受 gate 参数但代码里写死 run_gate()，
        导致每个 gate 测试都递归跑真 fastcheck，pytest 卡死 14 分钟。
        """
        called = []

        def fake_gate() -> int:
            called.append(True)
            return 0

        (repo / "new.txt").write_text("dirty\n", encoding="utf-8")
        finish_verified("test: 注入 gate 必须被调用", gate=fake_gate, repo_root=repo)
        assert called == [True], "注入的 gate 没被调用——finish_verified 无视了 gate 参数"

    def test_injected_gate_path_never_runs_real_quality_gate(self, repo):
        """反向守护：注入 gate 时，run_gate / _run_quality_gate 一次都不能碰。

        为什么需要这个：上面那个正向测试（fake_gate 被调）在 bug 复发时会先
        真的去跑 run_gate() → 真 fastcheck → 递归 hang，根本走不到 assert。
        这里用 mock 把真 gate 挡掉，即使代码走错分支也是毫秒级红，不 hang。
        """
        from unittest.mock import patch

        import amta.common.state_manager as sm

        (repo / "new.txt").write_text("dirty\n", encoding="utf-8")
        with patch.object(sm, "run_gate") as mock_run_gate, \
             patch.object(sm, "_run_quality_gate") as mock_qg:
            mock_qg.return_value = 0
            finish_verified("test: 注入时不跑真 gate", gate=_gate_passes, repo_root=repo)

        mock_run_gate.assert_not_called()
        mock_qg.assert_not_called()

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


class TestGateReportHonestVerdict:
    """GateReport.passed 必须诚实——fastcheck 红了就必须红（2026-10-08 修后门）。

    后门长这样：`rc == 0 or not self.new_failures`。当 ruff/depguard 挂了、
    pytest 没跑到时，new_failures 是空列表，`not []` = True，gate 照样 PASS。
    下面锁住四种形状，关键是前两种。
    """

    def _report(self, rc: int, failing: list[str], baseline: set[str] | None = None):
        from amta.common.state_manager import GateReport
        return GateReport(
            fastcheck_returncode=rc,
            pytest_failing=failing,
            baseline=baseline or set(),
        )

    def test_rc_zero_is_pass_regardless_of_failing(self):
        """fastcheck 绿 = 绿（pytest 失败列表不影响 verdict——rc 已经是 fastcheck 的事）。"""
        r = self._report(0, ["tests/x.py::test_y"])
        assert r.passed is True

    def test_rc_nonzero_with_empty_failing_is_fail(self):
        """关键：fastcheck 红 + pytest 失败列表为空 = 必须红。

        这就是后门曾经放行的场景（ruff 挂了、pytest 根本没跑成）。
        """
        r = self._report(1, [])
        assert r.passed is False, "后门复活：rc=1 但 failing 为空时放行了"

    def test_rc_nonzero_with_new_failure_is_fail(self):
        r = self._report(1, ["tests/x.py::test_y"], baseline=set())
        assert r.passed is False

    def test_rc_nonzero_with_only_baseline_reds_is_still_fail(self):
        """既有红不再放行——baseline 只用于 render 显示，不影响 verdict。"""
        r = self._report(1, ["tests/old.py::test_z"], baseline={"tests/old.py::test_z"})
        assert r.passed is False, "既有红竟然放行了 gate"


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
