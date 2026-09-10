"""state_manager — 对话状态管理（合并 context-bootstrap + finisher）。

Embedded 模式：不是"告诉 AI 去跑 git log"，是"调用一个函数就拿到所有状态"。

三层接口：
- bootstrap(): 对话开始，读取 git + env 状态，返回统一格式的 StateSnapshot
- finish(summary): 对话结束，git add + git commit（纯机制，不质检）
- finish_verified(summary): **对话结束的强制收口**——先跑完整质检，红了拒绝提交

为什么 finish_verified 存在（2026-09-10 事故）：全量 pytest 红了约两天无人察觉。
原因不是"没有质检"，而是唯一的 commit 拦截层（pre-commit）只跑 `fastcheck --quick`
（跳过 pytest），而交接文档把那次 QUICK PASS 记成了"关卡通过"——半扇门签发了假的通过。
修法刻意不是再造一个 doctor 工具（那只会变成第三层各跑一段的护栏），
而是把完整质检钉在**已经必须经过的那个收口点**上。

设计原则：
- 状态格式统一，AI 不需要解析多种输出
- 可测试，行为确定
- 不写文档，不写 progress.md，所有状态都在 git 里
"""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from amta.common.encoding import run_text, run_text_or
from amta.common.paths import ROOT


@dataclass
class StateSnapshot:
    """对话状态快照——统一格式，AI 容易解析。"""
    git_log: str
    git_diff: str
    git_status: str
    env_status: str
    branch: str
    dirty: bool

    def __str__(self) -> str:
        """转字符串时用清晰的 section 分隔，AI 容易解析。"""
        lines = [
            "=== STATE SNAPSHOT ===",
            f"branch: {self.branch}",
            f"dirty: {self.dirty}",
            "",
            "=== GIT LOG ===",
            self.git_log.strip(),
            "",
            "=== GIT DIFF ===",
            self.git_diff.strip() or "(clean)",
            "",
            "=== GIT STATUS ===",
            self.git_status.strip() or "(clean)",
            "",
            "=== ENV ===",
            self.env_status.strip(),
            "",
            "=== END ===",
        ]
        return "\n".join(lines)


class StateManager:
    """对话状态管理器。

    用法：
        sm = StateManager()  # 默认用当前仓库
        snap = sm.bootstrap()  # 对话开始，读取状态
        print(snap)
        # ... 干活 ...
        sm.finish("feat: 做了什么")  # 对话结束，commit
    """

    def __init__(self, repo_root: Path | str | None = None) -> None:
        """初始化。

        Args:
            repo_root: git 仓库根目录。None 表示用当前目录（自动向上找 .git）。
        """
        if repo_root is None:
            # 自动找仓库根（走 encoding 收口点：UTF-8 解码，不含宿主 locale）
            result = run_text(["git", "rev-parse", "--show-toplevel"], timeout=10)
            if result.returncode != 0 or not result.stdout.strip():
                raise RuntimeError(
                    "不在 git 仓库内，无法自动定位 repo_root；请显式传 repo_root",
                )
            self.repo_root = Path(result.stdout.strip())
        else:
            self.repo_root = Path(repo_root)

    def _run_git(self, *args: str) -> str:
        """跑 git 命令，返回 stdout。失败/超时返回空串。

        返回类型**永远是 str**：曾经用 `subprocess.run(text=True)` 时，中文 commit
        message 会让解码在 reader thread 内失败并静默产出 `stdout=None`，
        一路传到 `StateSnapshot.__str__` 炸成 AttributeError。
        """
        return run_text_or(["git", *args], cwd=self.repo_root, timeout=10)

    def bootstrap(self, env_check: bool = True) -> StateSnapshot:
        """对话开始：读取 git + env 状态，返回 StateSnapshot。

        Args:
            env_check: 是否跑环境自检。默认 True。

        Returns:
            StateSnapshot: 统一格式的状态快照。
        """
        git_log = self._run_git("log", "--oneline", "-10")
        git_diff = self._run_git("diff", "--stat")
        git_status = self._run_git("status", "--short")
        branch = self._run_git("branch", "--show-current").strip() or "unknown"
        dirty = bool(git_status.strip())

        env_status = ""
        if env_check:
            # 环境自检（只读检查，不自动修复）
            try:
                import contextlib

                # 用 StringIO 捕获输出
                import io

                from amta.common.environment import run_environment_check
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    run_environment_check([])
                env_status = buf.getvalue()
            except Exception:
                env_status = "env check skipped (error)"

        return StateSnapshot(
            git_log=git_log,
            git_diff=git_diff,
            git_status=git_status,
            env_status=env_status,
            branch=branch,
            dirty=dirty,
        )

    def is_dirty(self) -> bool:
        """工作区是否有未提交改动。"""
        return bool(self._run_git("status", "--short").strip())

    def finish(self, summary: str, tag: str | None = None) -> None:
        """对话结束：git add + git commit（纯机制，不做质检）。

        要"质检不过就拒绝落盘"请用模块级 `finish_verified()`——那是收口层，
        本方法保持单一职责，方便测试与被其他流程复用。

        Args:
            summary: commit message。不能为空或只有空白。
            tag: 如果是里程碑，打 tag。默认 None。

        Raises:
            ValueError: summary 为空或只有空白。
        """
        if not summary or not summary.strip():
            raise ValueError("summary 不能为空，commit message 必须有意义")

        # 检查是否有改动
        if not self.is_dirty():
            # 没有改动，不 commit（避免空 commit）
            return

        # git add + commit
        self._run_git("add", "-A")
        self._run_git("commit", "-m", summary.strip())

        # 打 tag（如果是里程碑）
        if tag:
            self._run_git("tag", tag)


class QualityGateFailed(RuntimeError):
    """质检未通过 → 拒绝落盘。"""

    def __init__(self, returncode: int) -> None:
        super().__init__(
            f"质检未通过（exit {returncode}）：已拒绝提交，改动原样留在工作区。"
            "先修红项；确实要绕过就用 --skip-check（会在收尾输出里留痕）",
        )
        self.returncode = returncode


def quality_gate_command() -> list[str]:
    """完整质检命令：`scripts/fastcheck.py` 全量（含 pytest）。

    刻意**不是** `--quick`：--quick 跳过 pytest，而 2026-09-10 的事故正是
    "只有半扇门在拦，却按整扇门记账"。
    """
    return [sys.executable, str(ROOT / "scripts" / "fastcheck.py")]


def _run_quality_gate() -> int:
    """跑完整质检，返回退出码（stdio 继承，让 AI 直接看到红在哪一步）。"""
    return subprocess.run(quality_gate_command(), cwd=str(ROOT)).returncode


def finish_verified(
    summary: str,
    tag: str | None = None,
    *,
    gate: Callable[[], int] | None = None,
    repo_root: Path | str | None = None,
    skip_check: bool = False,
) -> None:
    """对话结束的强制收口：先质检，红了拒绝落盘。

    Args:
        summary: commit message（不能为空）。
        tag: 里程碑 tag。
        gate: 质检函数，返回退出码。None 表示用真实的完整 fastcheck（约 107s）。
            可注入是给测试用的接缝——不需要真跑两分钟验证"红了会不会拒绝"。
        repo_root: git 仓库根。
        skip_check: 逃生门，显式跳过质检。

    Raises:
        ValueError: summary 为空。
        QualityGateFailed: 质检退出码非零（且未 skip_check）。
    """
    if not summary or not summary.strip():
        raise ValueError("summary 不能为空，commit message 必须有意义")

    manager = StateManager(repo_root=repo_root)

    # 无改动 = 无事发生：不跑质检（别为 107 秒的空转买单），也不提交
    if not manager.is_dirty():
        return

    if not skip_check:
        code = (gate or _run_quality_gate)()
        if code != 0:
            raise QualityGateFailed(code)

    manager.finish(summary, tag=tag)
