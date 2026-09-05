"""scripts/memory.py 统一 CLI 的冒烟测试（回归门：归档 memory_*.py 后单一入口仍可用）。

探针契约：统一 CLI 的只读子命令（index/grep/recent/status/lint/inject --stdout）能经
真实仓库跑通并返回 0。全部只读：index/grep/recent/status/lint 不写文件，inject 用 --stdout。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "memory.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), timeout=90,
    )


def test_index_lists_lessons() -> None:
    # 探针：estate 索引经统一 CLI 读出（归档后唯一入口仍工作）
    r = _run("index", "--type", "lessons")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip()


def test_grep_known_term_or_empty_ok() -> None:
    # grep 输出 0 或命中都算通（契约：返回条目级命中行或明确的无命中提示）
    r = _run("grep", "--query", "教训", "--limit", "5")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip()


def test_recent_exit_zero() -> None:
    r = _run("recent")
    assert r.returncode == 0, r.stderr


def test_status_exit_zero() -> None:
    r = _run("status")
    assert r.returncode == 0, r.stderr


def test_lint_non_strict_exit_zero() -> None:
    r = _run("lint")
    assert r.returncode == 0, r.stderr


def test_inject_stdout_non_empty() -> None:
    r = _run("inject", "--stdout")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip()
