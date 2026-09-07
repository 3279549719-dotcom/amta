"""Lessons 机械化守卫 — 把"机器可判、曾只靠散文"的坑锁成 pytest。

规则：一条 lesson 若能写成跑一次就知道对错的检查，就锁在这里（真强制层），
不靠 agent 记得去查 lessons.md。本文件只放机器可判的：
  - L5  ：含中文/非ASCII 的 .ps1 必须 UTF-8 带 BOM（PS5.1 按 GBK 误读中文路径）
  - L42 ：core.hooksPath 必须绝对路径且指向存在目录（相对值会静默失效=guard 死亡）

机器判不了的启发（选型/环境姿势）不锁这里，留 lessons.md 一句话。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"

# 不算入 BOM 检查的目录（依赖/构建物，非本项目手写 .ps1）
_EXCLUDE_DIRS = {".git", ".venv", "node_modules", ".claude", "__pycache__", "output"}


def _repo_ps1_files() -> list[Path]:
    """仓库内所有 .ps1（排除依赖/产物目录）。"""
    out: list[Path] = []
    for p in REPO_ROOT.rglob("*.ps1"):
        if any(part in _EXCLUDE_DIRS for part in p.relative_to(REPO_ROOT).parts):
            continue
        out.append(p)
    return out


def test_L5_ps1_with_nonascii_must_have_utf8_bom() -> None:
    """含中文/非 ASCII 的 .ps1 必须 UTF-8 带 BOM（否则 PS5.1 按 GBK 误读中文路径）。"""
    violations: list[str] = []
    for p in _repo_ps1_files():
        raw = p.read_bytes()
        if not raw:  # 空文件无编码问题
            continue
        try:
            raw.decode("ascii")
            continue  # 纯 ASCII，PS5.1 不会误读，无需 BOM
        except UnicodeDecodeError:
            pass
        # 含非 ASCII → 必须有 UTF-8 BOM
        if not raw.startswith(BOM):
            violations.append(str(p))
    assert not violations, (
        "以下 .ps1 含非 ASCII 但缺 UTF-8 BOM（PS5.1 会按 GBK 误读中文路径，见 L5）:\n"
        + "\n".join(violations)
    )


def test_L42_hookspath_is_absolute_and_resolvable() -> None:
    """core.hooksPath 必须绝对路径且指向存在的 .githooks（相对值在根移动/跨 cwd 下静默失效）。"""
    r = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0, "git config core.hooksPath 未设置 —— hook 门禁根本不在（L42）"
    val = r.stdout.strip()
    assert val.startswith("/") or (len(val) > 1 and val[1] == ":"), (
        f"core.hooksPath 必须是绝对路径，当前是相对值: {val!r}（会静默失效，见 L42）"
    )
    hooks_dir = Path(val)
    assert hooks_dir.is_dir(), f"core.hooksPath 指向的目录不存在: {val}"
    # pre-commit 已按 5fac83f 停用（改名 .disabled）；合 main 前唯一 git 验证门是 pre-push
    assert (hooks_dir / "pre-push").exists(), f"hooksPath 目录缺 pre-push: {val}"
