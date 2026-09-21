"""Lessons 机械化守卫 — 把"机器可判、曾只靠散文"的坑锁成 pytest。

规则：一条 lesson 若能写成跑一次就知道对错的检查，就锁在这里（真强制层），
不靠 agent 记得去查 lessons.md。本文件只放机器可判的：
  -   ：含中文/非ASCII 的 .ps1 必须 UTF-8 带 BOM（PS5.1 按 GBK 误读中文路径）
  -  ：core.hooksPath 必须绝对路径且指向存在目录（相对值会静默失效 = guard 死亡）
  - L50：活文件里不得出现裸 HTML（报告必须走 src/amta/report/ 深接口；probes/、archive/ 是草稿区）

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
        "以下 .ps1 含非 ASCII 但缺 UTF-8 BOM（PS5.1 会按 GBK 误读中文路径）:\n"
        + "\n".join(violations)
    )


def test_L42_hookspath_is_absolute_and_resolvable() -> None:
    """core.hooksPath 必须绝对路径且指向存在的 .githooks（相对值在根移动/跨 cwd 下静默失效）。"""
    r = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0, "git config core.hooksPath 未设置 —— hook 门禁根本不在"
    val = r.stdout.strip()
    assert val.startswith("/") or (len(val) > 1 and val[1] == ":"), (
        f"core.hooksPath 必须是绝对路径，当前是相对值: {val!r}（会静默失效）"
    )
    hooks_dir = Path(val)
    assert hooks_dir.is_dir(), f"core.hooksPath 指向的目录不存在: {val}"
    # pre-commit 已按 5fac83f 停用（改名 .disabled）；合 main 前唯一 git 验证门是 pre-push
    assert (hooks_dir / "pre-push").exists(), f"hooksPath 目录缺 pre-push: {val}"


# ---------------------------------------------------------------------------
# L50 — HTML 报告铁律的探针
# ---------------------------------------------------------------------------

# 裸 HTML 的判据（出现任一即视为"自己手写了一份 HTML 报告"）。
# 故意拆成两段隐式拼接：否则本文件自己也含这两个字面量 → 守卫抓自己。
_HTML_MARKERS = ("<!DOCT" + "YPE", "<ht" + "ml")

# 只扫**活文件**：src / scripts / tests。
# 不 rglob 全仓 —— reference/（第三方克隆）与 research/（历史记录）里的 HTML 是当时的事实，
# 报错等于伪造历史，并会让守卫永久变红 → 被人关掉。同 test_reference_integrity 的原则。
_HTML_SCAN_ROOTS = ("src", "scripts", "tests")

# 允许写裸 HTML 的区（按路径前缀匹配）：
#   - src/amta/report/  深接口本体，铁律要求所有人都用它，它自己当然得写 HTML
#   - scripts/probes/   草稿区：一次性可视化实验，用完即弃，不算生产路径
#   - scripts/archive/  归档区：历史脚本，冻结不改
_HTML_ALLOWED_PREFIXES = (
    ("src", "amta", "report"),
    ("scripts", "probes"),
    ("scripts", "archive"),
)


def _ad_hoc_html_files() -> list[str]:
    """活文件里手写裸 HTML 的 .py（repo 相对路径，已按允许区过滤）。"""
    violations: list[str] = []
    for root in _HTML_SCAN_ROOTS:
        root_dir = REPO_ROOT / root
        if not root_dir.is_dir():
            continue
        for p in root_dir.rglob("*.py"):
            rel = p.relative_to(REPO_ROOT)
            parts = rel.parts
            if any(part in _EXCLUDE_DIRS for part in parts):
                continue
            if any(parts[: len(prefix)] == prefix for prefix in _HTML_ALLOWED_PREFIXES):
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            if any(marker in text for marker in _HTML_MARKERS):
                violations.append(str(rel).replace("\\", "/"))
    return sorted(violations)


def test_L50_no_ad_hoc_html_report() -> None:
    """HTML 报告必须出自 `src/amta/report/` 深接口（CLAUDE.md 第 53 行「HTML 报告铁律」的探针）。

    2026-09-20 实证：这条铁律只活在散文里，一天内 scripts/probes/ 新写 4 个手写 HTML
    生成器（~170 行）没有任何机制会失败。散文拦不住人，断言才行。
    草稿区（probes/、archive/）与深接口本体（src/amta/report/）是显式允许区，见
    `_HTML_ALLOWED_PREFIXES`。
    """
    violations = _ad_hoc_html_files()
    assert not violations, (
        "以下活文件里手写了裸 HTML —— 违反 CLAUDE.md「HTML 报告铁律」"
        "（必须用 src/amta/report/ 深接口，禁止 scripts/ 下新建独立 HTML 生成脚本）:\n"
        + "\n".join(f"  {v}" for v in violations)
        + "\n\n改法：生产报告走 `scripts/gen_report.py`（深接口在 src/amta/report/）；"
        "一次性的可视化实验挪到 `scripts/probes/`（草稿区，不受此限）。"
    )
