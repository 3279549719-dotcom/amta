"""test_state_finish_stowaway — 收尾夹带检查（2026-10-01 事故驱动，同类第二次）。

## 事故

`state.py finish` 内部的 `git add -A` 把**用户自己改的两个文件**
（`.dsh/skills/handoff/SKILL.md`、`.gitignore`）一并提交进收尾 commit，
违反本项目"不得提交用户自有改动"的边界（同类第一次在 2026-09-17）。

上一轮的对策是往 `.git/info/exclude` 里加路径——但它**只能挡未跟踪文件**，
挡不住已跟踪文件的改动，所以那次事故照样发生。

## 修法

`finish` 不再 `git add -A`：

1. `commit_plan()` 把工作区变动分成「将提交」与「不动（用户自有）」；
2. 判据不新造名单，而是复用 `.git/info/exclude`（gitignore 语法），
   并**问 git 自己**（`git check-ignore --no-index`）有没有命中；
3. 只 `git add` 清单里「将提交」的路径；
4. 清单永远打印，且带**扫描计数**（L58：守卫必须自证扫了什么）。

下面第一条测试就是对那次事故的复现——它在旧实现下必红（旧代码会把用户文件一起提交）。
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from amta.common.encoding import run_text
from amta.common.paths import ROOT
from amta.common.state_manager import (
    GitCommandFailed,
    StateManager,
    finish_verified,
)

USER_FILE = "user_owned.txt"
SESSION_FILE = "session_work.txt"


def _git(repo, *args: str) -> str:
    """跑 git 并正确解码（不用 `text=True`：那会按宿主 locale 解中文）。"""
    return run_text(["git", *args], cwd=repo).stdout


@pytest.fixture
def repo(tmp_path):
    """一个干净仓库：`user_owned.txt` 已跟踪（模拟"用户自己的文件"）。"""
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init"], cwd=r, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=r, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=r, capture_output=True, check=True)
    (r / USER_FILE).write_text("user wrote this\n", encoding="utf-8")
    (r / "a.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=r, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=r, capture_output=True, check=True)
    return r


def declare_user_owned(repo, *patterns: str) -> None:
    """把路径写进 `.git/info/exclude`——这是既有的"用户自有"声明，不新造名单。"""
    exclude = repo / ".git" / "info" / "exclude"
    text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    exclude.write_text(text + "\n" + "\n".join(patterns) + "\n", encoding="utf-8")


def head(repo) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


def committed_paths(repo) -> list[str]:
    return [p for p in _git(repo, "show", "--name-only", "--format=", "HEAD").splitlines() if p]


def _gate_passes() -> int:
    return 0


class TestStowawayIsNotCommitted:
    """核心：用户自有的已跟踪文件不得被收尾扫走（2026-10-01 事故复现）。"""

    def test_user_owned_tracked_change_is_not_committed(self, repo):
        """旧实现（`git add -A`）在这里必红：用户文件会被一起提交。"""
        declare_user_owned(repo, USER_FILE)
        (repo / USER_FILE).write_text("user edited this themselves\n", encoding="utf-8")
        (repo / SESSION_FILE).write_text("agent work\n", encoding="utf-8")

        finish_verified("feat: 只提交本次任务", gate=_gate_passes, repo_root=repo)

        committed = committed_paths(repo)
        assert SESSION_FILE in committed, "本次任务的产物没被提交"
        assert USER_FILE not in committed, "用户自有改动被扫进了收尾提交——事故复现"

    def test_user_owned_change_stays_in_worktree(self, repo):
        """不提交 ≠ 弄丢：用户改动必须原样留在工作区。"""
        declare_user_owned(repo, USER_FILE)
        (repo / USER_FILE).write_text("user edited this themselves\n", encoding="utf-8")
        (repo / SESSION_FILE).write_text("agent work\n", encoding="utf-8")

        finish_verified("feat: x", gate=_gate_passes, repo_root=repo)

        status = _git(repo, "status", "--porcelain", "--untracked-files=all")
        assert USER_FILE in status, "用户改动既没提交也没留在工作区——被吞了"
        assert (repo / USER_FILE).read_text(encoding="utf-8") == "user edited this themselves\n"


class TestPlanIsReported:
    """清单必须自证：扫了几个路径、命中几条模式、两堆各是什么。"""

    def test_plan_splits_included_and_excluded(self, repo):
        declare_user_owned(repo, USER_FILE)
        (repo / USER_FILE).write_text("mine\n", encoding="utf-8")
        (repo / SESSION_FILE).write_text("theirs\n", encoding="utf-8")

        plan = StateManager(repo_root=repo).commit_plan()

        assert [c.path for c in plan.included] == [SESSION_FILE]
        assert [c.path for c in plan.excluded] == [USER_FILE]

    def test_plan_reports_scan_size_and_pattern_count(self, repo):
        """L58：算出来的检查必须报告它扫了什么，否则"0 命中"与"没扫"不可区分。"""
        declare_user_owned(repo, USER_FILE, "logs/")
        (repo / SESSION_FILE).write_text("x\n", encoding="utf-8")

        plan = StateManager(repo_root=repo).commit_plan()

        assert plan.scanned == 1, "扫描计数不对：清单没有自证它扫了几个路径"
        assert plan.patterns == 2, "没报告用户自有声明里有几条模式"
        text = plan.render()
        assert "扫描：工作区变动 1 个路径" in text
        assert ".git/info/exclude" in text, "清单没写明判据来自哪里"

    def test_render_lists_both_buckets_even_when_empty(self, repo):
        """两堆为空也要打印——空清单和"没打印"必须长得不一样。"""
        (repo / SESSION_FILE).write_text("x\n", encoding="utf-8")
        text = StateManager(repo_root=repo).commit_plan().render()
        assert "将提交（1）" in text
        assert "不动（用户自有，0）" in text

    def test_precise_reason_names_the_pattern_and_line(self, repo):
        """报告要说清"凭什么不动它"——模式原文 + 声明文件行号，便于人核对。"""
        declare_user_owned(repo, USER_FILE)
        (repo / USER_FILE).write_text("mine\n", encoding="utf-8")

        plan = StateManager(repo_root=repo).commit_plan()

        assert [c.path for c in plan.excluded] == [USER_FILE]
        reason = StateManager(repo_root=repo).user_owned_hits([USER_FILE])[USER_FILE]
        assert USER_FILE in reason
        assert ".git/info/exclude" in reason
        assert ":" in reason, "没给出行号，人无法快速核对是哪条模式"


class TestNothingToDoMeansNothingHappens:
    """全部改动都是用户自有时：不跑质检、不产生空 commit。"""

    def test_all_user_owned_skips_gate_and_commit(self, repo):
        declare_user_owned(repo, USER_FILE)
        (repo / USER_FILE).write_text("mine\n", encoding="utf-8")
        before = head(repo)
        called: list[bool] = []

        def gate() -> int:
            called.append(True)
            return 0

        report = finish_verified("chore: 无事发生", gate=gate, repo_root=repo)

        assert called == [], "只剩用户自有改动，却还是跑了 107 秒质检"
        assert head(repo) == before
        assert report.committed is False

    def test_clean_tree_still_skips_gate(self, repo):
        called: list[bool] = []

        def gate() -> int:
            called.append(True)
            return 0

        finish_verified("chore: 干净", gate=gate, repo_root=repo)
        assert called == []


class TestDryRun:
    """`--dry-run`：先看清单，再决定要不要落盘。"""

    def test_dry_run_reports_without_committing(self, repo):
        declare_user_owned(repo, USER_FILE)
        (repo / USER_FILE).write_text("mine\n", encoding="utf-8")
        (repo / SESSION_FILE).write_text("work\n", encoding="utf-8")
        before = head(repo)

        report = finish_verified("feat: x", gate=_gate_passes, repo_root=repo, dry_run=True)

        assert head(repo) == before, "dry-run 却产生了提交"
        assert report.committed is False
        assert "dry-run" in report.reason

    def test_dry_run_does_not_run_the_gate(self, repo):
        (repo / SESSION_FILE).write_text("work\n", encoding="utf-8")
        called: list[bool] = []

        def gate() -> int:
            called.append(True)
            return 1

        finish_verified("feat: x", gate=gate, repo_root=repo, dry_run=True)
        assert called == []

    def test_cli_dry_run_prints_manifest_and_commits_nothing(self, repo):
        """CLI 层：清单必须真的打到 stdout（它是"提交了什么"的唯一证据）。"""
        declare_user_owned(repo, USER_FILE)
        (repo / USER_FILE).write_text("mine\n", encoding="utf-8")
        (repo / SESSION_FILE).write_text("work\n", encoding="utf-8")
        before = head(repo)

        result = run_text(
            [sys.executable, str(ROOT / "scripts" / "state.py"), "finish", "feat: x", "--dry-run"],
            cwd=repo, timeout=60,
        )

        assert result.returncode == 0, result.stderr
        assert "收尾清单" in result.stdout
        assert SESSION_FILE in result.stdout
        assert USER_FILE in result.stdout
        assert head(repo) == before, "CLI dry-run 却产生了提交"


class TestNoDeclarationNoChange:
    """没有用户自有声明时，行为与以前一致（不许误伤正常收尾）。"""

    def test_everything_is_committed_without_declaration(self, repo):
        (repo / SESSION_FILE).write_text("work\n", encoding="utf-8")
        StateManager(repo_root=repo).finish("feat: 正常收尾")
        assert SESSION_FILE in committed_paths(repo)

    def test_default_exclude_file_matches_nothing(self, repo):
        """`git init` 自带的 exclude 只有注释行 → 0 模式、0 命中，不许误判。"""
        plan = StateManager(repo_root=repo).commit_plan()
        assert plan.patterns == 0
        assert plan.excluded == []

    def test_untracked_user_file_is_hidden_by_git_itself(self, repo):
        """未跟踪且被 ignore 的文件根本不进清单（git 自己挡第一层）。"""
        declare_user_owned(repo, "scratch/")
        (repo / "scratch").mkdir()
        (repo / "scratch" / "note.md").write_text("mine\n", encoding="utf-8")
        (repo / SESSION_FILE).write_text("work\n", encoding="utf-8")

        plan = StateManager(repo_root=repo).commit_plan()

        assert [c.path for c in plan.included] == [SESSION_FILE]


class TestScanFailureIsLoud:
    """扫不到 ≠ 干净：读失败必须炸，不能降级成"没有改动"。"""

    @pytest.fixture
    def broken_repo(self, repo):
        """让 `git status` 确定性地失败：把 index 写成垃圾字节。

        刻意**不**用"找一个不在仓库里的目录"这种做法：系统临时目录
        （`C:/Users/asus/AppData/Local/Temp`）实测落在 `C:/Users/asus/.git` 这个
        上层仓库里，于是"不在仓库内"根本构造不出来——第一版就是这么变成
        **静默 skip** 的（skip 的守卫等于没有守卫，正是 L58 说的事）。
        index 损坏无环境依赖，永远 rc=128。
        """
        (repo / ".git" / "index").write_bytes(b"GARBAGE")
        return repo

    def test_status_failure_raises_instead_of_reporting_clean(self, broken_repo):
        with pytest.raises(GitCommandFailed):
            StateManager(repo_root=broken_repo).changed_paths()

    def test_finish_propagates_scan_failure(self, broken_repo):
        with pytest.raises(GitCommandFailed):
            StateManager(repo_root=broken_repo).finish("feat: x")

    def test_already_staged_user_path_is_reported(self, repo):
        """已在暂存区的用户自有路径会随本次 commit 走 → 必须在清单里现身。"""
        declare_user_owned(repo, USER_FILE)
        (repo / USER_FILE).write_text("mine\n", encoding="utf-8")
        (repo / SESSION_FILE).write_text("work\n", encoding="utf-8")
        _git(repo, "add", USER_FILE)

        plan = StateManager(repo_root=repo).commit_plan()

        assert USER_FILE in plan.already_staged, "已在暂存区的路径没被列出来"
        assert "已在暂存区" in plan.render()
