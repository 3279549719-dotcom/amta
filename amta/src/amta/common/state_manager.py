"""state_manager — 对话状态管理（合并 context-bootstrap + finisher）。

Embedded 模式：不是"告诉 AI 去跑 git log"，是"调用一个函数就拿到所有状态"。

两个接口：
- bootstrap(): 对话开始，读取 git + env 状态，返回统一格式的 StateSnapshot
- finish(summary): 对话结束，git add + git commit

设计原则：
- 状态格式统一，AI 不需要解析多种输出
- 可测试，行为确定
- 不写文档，不写 progress.md，所有状态都在 git 里
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from amta.common.encoding import run_text, run_text_or


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

    def finish(self, summary: str, tag: str | None = None) -> None:
        """对话结束：git add + git commit。

        Args:
            summary: commit message。不能为空或只有空白。
            tag: 如果是里程碑，打 tag。默认 None。

        Raises:
            ValueError: summary 为空或只有空白。
        """
        if not summary or not summary.strip():
            raise ValueError("summary 不能为空，commit message 必须有意义")

        # 检查是否有改动
        status = self._run_git("status", "--short")
        if not status.strip():
            # 没有改动，不 commit（避免空 commit）
            return

        # git add + commit
        self._run_git("add", "-A")
        self._run_git("commit", "-m", summary.strip())

        # 打 tag（如果是里程碑）
        if tag:
            self._run_git("tag", tag)
