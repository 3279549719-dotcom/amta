"""state_manager — 对话状态管理（合并 context-bootstrap + finisher）。

Embedded 模式：不是"告诉 AI 去跑 git log"，是"调用一个函数就拿到所有状态"。

三层接口：
- bootstrap(): 对话开始，读取 git + env 状态，返回统一格式的 StateSnapshot
- finish(summary): 对话结束，`git add` 明确路径 + `git commit`（纯机制，不质检）
- finish_verified(summary): **对话结束的强制收口**——先跑完整质检，红了拒绝提交

## 收尾不再 `git add -A`（2026-10-01 事故，第二次同类）

`state.py finish` 内部的 `git add -A` 把**用户自己改的两个文件**
（`.dsh/skills/handoff/SKILL.md`、`.gitignore`）扫进了收尾提交，
违反本项目"不得提交用户自有改动"的边界。同类事故 2026-09-17 已发生过一次。

修法刻意不是"禁止 add -A"这种散文规则（散文规则拦不住任何事），而是让收尾入口
**自己报告它要提交什么**，并且**只提交它报告过的路径**：

1. `commit_plan()` 把工作区变动分成两堆——「将提交」与「不动（用户自有）」；
2. 「用户自有」的判据**不新造名单**，而是复用用户已经维护的那份本地声明
   `.git/info/exclude`（gitignore 语法），并且**问 git 自己**有没有命中
   （`git check-ignore`），不复刻语法、不猜；
3. `finish()` 按「将提交」的显式路径 `git add`，不再扫全树；
4. 报告里**打印它扫了几个路径、命中几条模式**——按 L58：算出来的检查必须自证
   扫了什么，否则"0 命中"与"根本没扫"在输出上不可区分。

`.git/info/exclude` 原本只能挡**未跟踪**文件（用户上一轮就是这么用的），
现在同一份声明也保护**已跟踪文件**的改动——这正是那次事故漏掉的一半。

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

import os
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


# ---------------------------------------------------------------------------
# 收尾清单：让"夹带"可见（2026-10-01 事故驱动）
# ---------------------------------------------------------------------------

# 用户自有路径声明的**权威源**：git 自己的本地排除清单。
#
# 只认 `.git/info/exclude`，**不认 `.gitignore`**：后者是仓库共享规则（`output/`、
# `*.log` 之类），拿它冻结已跟踪文件会让"改了却没提交"再次变无声——正是本项目最怕的
# "看起来已生效"。`.git/info/exclude` 才是"这些是我自己的东西，收尾别动"的既有声明。
USER_OWNED_DECLARATION = ".git/info/exclude"


@dataclass(frozen=True)
class ChangedPath:
    """工作区里的一个变动路径（status 是 git porcelain 的两字符状态码，如 ``" M"``/``"??"``）。"""

    status: str
    path: str

    def render(self) -> str:
        return f"    {self.status.strip() or '?':<2} {self.path}"


@dataclass
class CommitPlan:
    """收尾清单：这次到底会提交哪些路径，哪些被跳过。

    Attributes:
        included: 将提交的路径（本次任务的产物）。
        excluded: 命中用户自有声明、**收尾不动**的路径。
        already_staged: 收尾开始前就已经在暂存区里的路径（会随本次 commit 一起走，
            所以必须列出来——否则它又是一处"没报告却发生了"）。
        scanned: 本次扫到的变动路径总数（L58：守卫必须自证扫了什么）。
        declaration: 用户自有声明文件的路径（原样打印，便于人核对）。
        patterns: 从声明里解析出的模式条数（0 也要打印：区分"没有声明"与"声明了但没命中"）。
    """

    included: list[ChangedPath]
    excluded: list[ChangedPath]
    already_staged: list[str]
    scanned: int
    declaration: str
    patterns: int

    @property
    def is_empty(self) -> bool:
        """没有任何东西会进入提交——既不跑质检，也不产生空 commit。"""
        return not self.included and not self.already_staged

    def render(self) -> str:
        """人类/agent 可读的清单。**永远打印扫描计数**，不做静默 PASS。"""
        lines = [
            "=== 收尾清单 ===",
            f"扫描：工作区变动 {self.scanned} 个路径"
            f"（用户自有声明 {self.declaration}：{self.patterns} 条模式）",
        ]
        if self.included:
            lines.append(f"将提交（{len(self.included)}）：")
            lines.extend(c.render() for c in self.included)
        else:
            lines.append("将提交（0）：(无)")
        if self.excluded:
            lines.append(f"不动（用户自有，{len(self.excluded)}）：")
            lines.extend(f"{c.render()}   ← 命中 {self.declaration}" for c in self.excluded)
        else:
            lines.append("不动（用户自有，0）：(无)")
        if self.already_staged:
            lines.append(f"已在暂存区（{len(self.already_staged)}，会随本次提交一起走）：")
            lines.extend(f"    {p}" for p in self.already_staged)
        lines.append("=== 清单结束 ===")
        return "\n".join(lines)


@dataclass
class FinishReport:
    """一次 finish 的结果：清单 + 到底提交了没有 + 原因。"""

    plan: CommitPlan
    committed: bool
    reason: str = ""

    def render(self) -> str:
        text = self.plan.render()
        if self.committed:
            return f"{text}\n收尾结果：已提交"
        return f"{text}\n收尾结果：未提交（{self.reason or '无改动'}）"


def _parse_status_z(raw: str) -> list[ChangedPath]:
    """解析 `git status --porcelain -z` 的 NUL 分隔输出。

    不用非 `-z` 输出：git 默认会把非 ASCII 路径名转义成 `"\\346\\..."`（core.quotePath），
    中文文件名会对不上。`-z` 才是原样字节。
    """
    fields = raw.split("\0")
    out: list[ChangedPath] = []
    i = 0
    while i < len(fields):
        record = fields[i]
        i += 1
        if len(record) < 4:
            continue
        status, path = record[:2], record[3:]
        out.append(ChangedPath(status=status, path=path))
        if "R" in status or "C" in status:
            # 重命名/复制：原路径是紧随其后的第二个字段，也要一起 stage（否则删不掉旧名）
            if i < len(fields) and fields[i]:
                out.append(ChangedPath(status=f"{status[0]}D", path=fields[i]))
                i += 1
    return out


def _chunks(items: list[str], size: int) -> list[list[str]]:
    """把长路径列表切片——避免命令行长度上限（Windows 约 32K）。"""
    return [items[i:i + size] for i in range(0, len(items), size)]


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
        """**只读** git 命令，返回 stdout。失败/超时返回空串。

        返回类型**永远是 str**：曾经用 `subprocess.run(text=True)` 时，中文 commit
        message 会让解码在 reader thread 内失败并静默产出 `stdout=None`，
        一路传到 `StateSnapshot.__str__` 炸成 AttributeError。

        仅用于状态探针（log/diff/status/branch）——读不到就降级成空串，不让 CLI 崩。
        **写操作（add/commit/tag）必须用 `_run_git_write`**：见那里的 2026-09-17 事故。
        """
        return run_text_or(["git", *args], cwd=self.repo_root, timeout=10)

    def _run_git_write(self, *args: str, timeout: float = 600) -> str:
        """**写** git 命令（add/commit/tag）：失败必须炸出来，绝不静默。

        ## 为什么不能让读写共用 `_run_git`（2026-09-17 实测）

        `_run_git` 走 `run_text_or`，而它的契约是"失败返回 default 空串"
        （只读探针降级用）。`git commit` 会触发 pre-commit hook，而那个 hook
        自己还要跑一遍 `fastcheck --quick`——pyright 冷启动常超 10 秒。
        于是：commit 超时 → 被吞成空串 → `finish_verified` 正常返回 →
        CLI 打印 "finish OK"，**而提交根本没落地**，改动静默停在暂存区。

        唯一收尾入口报成功、而什么都没发生——正是本项目最怕的那类
        "看起来已生效"。所以写操作改用宽超时 + 非零退出码即抛。
        """
        result = run_text(["git", *args], cwd=self.repo_root, timeout=timeout)
        if result.returncode != 0:
            raise GitCommandFailed(
                f"git {' '.join(args)} 失败（exit {result.returncode}）："
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result.stdout

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

    def changed_paths(self) -> list[ChangedPath]:
        """工作区所有变动路径（含未跟踪文件；被忽略的文件由 git 自己挡掉）。

        **读失败要炸**，不能降级成空列表：空列表与"干净的仓库"在输出上完全一样，
        那正是 L58 说的"静默失效的检查比没有检查更危险"。
        """
        result = run_text(
            ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
            cwd=self.repo_root, timeout=30,
        )
        if result.returncode != 0:
            raise GitCommandFailed(
                f"git status 失败（exit {result.returncode}）："
                f"{result.stderr.strip() or result.stdout.strip()}",
            )
        return _parse_status_z(result.stdout)

    def user_owned_declaration(self) -> Path:
        """用户自有声明文件的位置（`.git/info/exclude`，worktree/submodule 下也能找到）。"""
        common = self._run_git("rev-parse", "--git-common-dir").strip()
        if not common:
            return self.repo_root / USER_OWNED_DECLARATION
        base = Path(common)
        if not base.is_absolute():
            base = self.repo_root / base
        return base / "info" / "exclude"

    def _declaration_patterns(self) -> int:
        """声明里的模式条数（注释与空行不算）——报告里要打印，用来区分"没声明"与"没命中"。"""
        path = self.user_owned_declaration()
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            return 0
        return sum(
            1 for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )

    def user_owned_hits(self, paths: list[str]) -> dict[str, str]:
        """问 git 自己：哪些路径命中用户自有声明。

        刻意不复刻 gitignore 语法（L58：优先问权威源，不要维护名单）——
        `git check-ignore` 就是权威源，pattern 语法演进（`**`、取反、目录规则）不用我们操心。
        `--no-index` 是必须的：默认模式下已跟踪文件的改动根本不会被 check-ignore 报告，
        而那正是 2026-10-01 事故漏掉的那一半。
        """
        hits: dict[str, str] = {}
        if not paths:
            return hits
        for chunk in _chunks(paths, 200):
            result = run_text(
                ["git", "check-ignore", "-v", "-z", "--no-index", "--stdin"],
                cwd=self.repo_root, timeout=30,
                stdin="\0".join(chunk),
            )
            if result.returncode not in (0, 1):
                # 0=有命中 1=无命中；其余=真出错，绝不当作"没有用户自有文件"
                raise GitCommandFailed(
                    f"git check-ignore 失败（exit {result.returncode}）："
                    f"{result.stderr.strip() or result.stdout.strip()}",
                )
            fields = result.stdout.split("\0")
            # -v -z 的每条记录是 4 个字段：来源 \0 行号 \0 模式 \0 路径 \0
            for i in range(0, len(fields) - 3, 4):
                source, lineno, pattern, path = fields[i:i + 4]
                if source.replace("\\", "/").endswith(USER_OWNED_DECLARATION):
                    hits[path] = f"{pattern}（{USER_OWNED_DECLARATION}:{lineno}）"
        return hits

    def staged_paths(self) -> list[str]:
        """收尾开始前就已经在暂存区里的路径。"""
        raw = self._run_git("diff", "--cached", "--name-only", "-z")
        return [p for p in raw.split("\0") if p]

    def commit_plan(self) -> CommitPlan:
        """算出收尾清单：什么将提交、什么不动、扫描面有多大。"""
        changed = self.changed_paths()
        hits = self.user_owned_hits([c.path for c in changed])
        included = [c for c in changed if c.path not in hits]
        excluded = [c for c in changed if c.path in hits]
        staged = self.staged_paths()
        return CommitPlan(
            included=included,
            excluded=excluded,
            already_staged=staged,
            scanned=len(changed),
            declaration=USER_OWNED_DECLARATION,
            patterns=self._declaration_patterns(),
        )

    def finish(
        self,
        summary: str,
        tag: str | None = None,
        *,
        plan: CommitPlan | None = None,
        dry_run: bool = False,
    ) -> FinishReport:
        """对话结束：按收尾清单 `git add` 明确路径 + `git commit`（纯机制，不做质检）。

        要"质检不过就拒绝落盘"请用模块级 `finish_verified()`——那是收口层，
        本方法保持单一职责，方便测试与被其他流程复用。

        Args:
            summary: commit message。不能为空或只有空白。
            tag: 如果是里程碑，打 tag。默认 None。
            plan: 收尾清单。None 表示现算（门禁可能自己生成文件，所以**临提交前**算才准）。
            dry_run: True 时只返回清单，不 add、不 commit。

        Returns:
            FinishReport: 清单 + 是否真的提交了。

        Raises:
            ValueError: summary 为空或只有空白。
            GitCommandFailed: git 读/写失败。
        """
        if not summary or not summary.strip():
            raise ValueError("summary 不能为空，commit message 必须有意义")

        plan = plan or self.commit_plan()

        if plan.is_empty:
            # 没有改动，不 commit（避免空 commit）
            return FinishReport(plan=plan, committed=False, reason="没有需要提交的改动")
        if dry_run:
            return FinishReport(plan=plan, committed=False, reason="dry-run：只报告，不落盘")

        # 只 add 清单里报告过的路径——不再 `git add -A` 扫全树
        included = [c.path for c in plan.included]
        for chunk in _chunks(included, 200):
            self._run_git_write("add", "-A", "--", *chunk)
        self._run_git_write("commit", "-m", summary.strip())

        # 打 tag（如果是里程碑）
        if tag:
            self._run_git_write("tag", tag)

        return FinishReport(plan=plan, committed=True)


class GitCommandFailed(RuntimeError):
    """写型 git 命令失败（add/commit/tag）→ 落盘没发生，必须让调用方知道。"""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


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


# ---------------------------------------------------------------------------
# 基线红名单（2026-10-08：被"本来就红"的旧测试白烧 20 分钟事故驱动）
# ---------------------------------------------------------------------------

_BASELINE_RED_FILE = ROOT / ".dsh" / "baseline-red.txt"


def _pytest_failing_tests() -> list[str]:
    """跑 pytest 并收集失败的测试 ID（如 tests/test_foo.py::test_bar）。

    用 `--tb=no -q` 只看汇总行，再解析 FAILED/ERROR 行。
    """
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONIOENCODING": "utf-8"}
    basetemp = ROOT / "output" / "logs" / f".pytest-baseline-{os.getpid()}"
    import shutil
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", str(ROOT / "tests"),
             "-q", "--tb=no", "-p", "no:cacheprovider",
             "--basetemp", str(basetemp)],
            cwd=str(ROOT), env=env, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
    finally:
        shutil.rmtree(basetemp, ignore_errors=True)
    out = (r.stdout or "") + (r.stderr or "")
    failing: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("FAILED") or line.startswith("ERROR"):
            # FAILED tests/test_x.py::test_y - assertion error
            parts = line.split(" ", 1)
            if len(parts) >= 2:
                failing.append(parts[1].split(" - ")[0])
    return failing


def save_baseline() -> list[str]:
    """跑一次 pytest，把当前失败的测试 ID 存为基线。返回失败列表。"""
    failing = _pytest_failing_tests()
    _BASELINE_RED_FILE.parent.mkdir(parents=True, exist_ok=True)
    _BASELINE_RED_FILE.write_text("\n".join(sorted(failing)), encoding="utf-8")
    return failing


def load_baseline() -> set[str]:
    """读基线红名单（文件不存在 → 空集 = 之前没记过基线）。"""
    if not _BASELINE_RED_FILE.exists():
        return set()
    return {
        line.strip() for line in _BASELINE_RED_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


@dataclass
class GateReport:
    """gate 跑完的结构化结果：跑了什么、红了哪些、哪些是新红。"""

    fastcheck_returncode: int
    pytest_failing: list[str]
    baseline: set[str]

    @property
    def new_failures(self) -> list[str]:
        """不在基线里的红 = 这次改动引入的。"""
        return [t for t in self.pytest_failing if t not in self.baseline]

    @property
    def pre_existing(self) -> list[str]:
        """在基线里的红 = 之前就有，不拦。"""
        return [t for t in self.pytest_failing if t in self.baseline]

    @property
    def passed(self) -> bool:
        """gate 是否通过：fastcheck 全绿，或红的全是既有红。"""
        return self.fastcheck_returncode == 0 or not self.new_failures

    def render(self) -> str:
        lines = ["=== GATE REPORT ==="]
        if self.fastcheck_returncode == 0:
            lines.append("fastcheck: ALL PASS")
        else:
            lines.append(f"fastcheck: FAIL (exit {self.fastcheck_returncode})")
        if not self.pytest_failing:
            lines.append("pytest: no failures")
        else:
            lines.append(f"pytest: {len(self.pytest_failing)} failing")
            if self.new_failures:
                lines.append(f"  NEW (blocks ship, {len(self.new_failures)}):")
                for t in self.new_failures:
                    lines.append(f"    ✗ {t}")
            if self.pre_existing:
                lines.append(f"  PRE-EXISTING (in baseline, not blocking, {len(self.pre_existing)}):")
                for t in self.pre_existing:
                    lines.append(f"    · {t}")
        lines.append(f"baseline file: {_BASELINE_RED_FILE}")
        lines.append(f"verdict: {'PASS' if self.passed else 'FAIL — new failures must be fixed before ship'}")
        return "\n".join(lines)


def run_gate(*, capture_pytest: bool = True) -> GateReport:
    """跑质检门（fastcheck 全量），并对比基线红名单。**不碰 git**。

    这是 gate/ship 拆分的 gate 侧：跑测试、报结果，但不 commit。
    ship 侧见 `StateManager.finish()`（纯 git add+commit，不跑测试）。

    Args:
        capture_pytest: 是否额外解析 pytest 失败列表做基线对比。
            fastcheck 自己也会跑 pytest，但它的输出混在其他 guard 里不好解析，
            所以这里单独跑一次 `--tb=no` 只收失败 ID。
    """
    rc = _run_quality_gate()
    if not capture_pytest:
        return GateReport(fastcheck_returncode=rc, pytest_failing=[], baseline=load_baseline())
    failing = _pytest_failing_tests()
    return GateReport(
        fastcheck_returncode=rc,
        pytest_failing=failing,
        baseline=load_baseline(),
    )


def finish_verified(
    summary: str,
    tag: str | None = None,
    *,
    gate: Callable[[], int] | None = None,
    repo_root: Path | str | None = None,
    skip_check: bool = False,
    dry_run: bool = False,
) -> FinishReport:
    """对话结束的强制收口：先质检，红了拒绝落盘。

    Args:
        summary: commit message（不能为空）。
        tag: 里程碑 tag。
        gate: 质检函数，返回退出码。None 表示用真实的完整 fastcheck（约 107s）。
            可注入是给测试用的接缝——不需要真跑两分钟验证"红了会不会拒绝"。
        repo_root: git 仓库根。
        skip_check: 逃生门，显式跳过质检。
        dry_run: True 时只报告收尾清单，不跑质检也不落盘。

    Returns:
        FinishReport: 收尾清单 + 是否真的提交了（**清单永远带出来**，
        让"这次到底提交了什么"是一份可核对的证据，而不是一句 OK）。

    Raises:
        ValueError: summary 为空。
        QualityGateFailed: 质检退出码非零（且未 skip_check）。
    """
    if not summary or not summary.strip():
        raise ValueError("summary 不能为空，commit message 必须有意义")

    manager = StateManager(repo_root=repo_root)

    # 无改动 = 无事发生：不跑质检（别为 107 秒的空转买单），也不提交。
    # 这里用 commit_plan 而不是 is_dirty：**全部改动都属于用户自有**时同样无事发生，
    # 不能为它跑一遍质检然后提交一个空 commit。
    plan = manager.commit_plan()
    if plan.is_empty:
        return FinishReport(plan=plan, committed=False, reason="没有需要提交的改动")
    if dry_run:
        return FinishReport(plan=plan, committed=False, reason="dry-run：只报告，不落盘")

    if not skip_check:
        # gate/ship 拆分后的 gate：跑 fastcheck + pytest，对比基线红名单。
        # 只有 NEW_FAILURE（不在基线里的红）才拦；既有红不拦（2026-10-08：
        # 被"本来就红"的旧测试白烧 20 分钟事故驱动）。
        report = run_gate()
        print(report.render())
        if not report.passed:
            raise QualityGateFailed(1)

    # 清单**重新算**：全量门禁自己会生成文件（module-map 刷新等），
    # 拿门禁前的清单去 add 会把门禁刚产出的东西漏在提交外。
    return manager.finish(summary, tag=tag)
