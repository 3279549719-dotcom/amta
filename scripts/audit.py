"""audit — 轻量 Harness 熵审计（/audit 的确定性部分）。

检查（可机械判定的）：
  1. CLAUDE.md 行数是否过大（阈值，避免无限膨胀）。
  2. docs/lessons.md 是否存在、每条是否含模板小节。
  3. docs/decisions/ 是否有 README 索引。
  4. output/ 下被入库的 JSON 是否可解析（复用 tests/test_output.py 的校验）。
  5. 是否有被 gitignore 的产物被意外提交（git ls-files 对比 .gitignore 关键目录）。

只输出"建议"，不自动改文件；exit 0 即使有建议（审计是咨询不是门禁）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CLAUDE_MAX_LINES = 120
LESSON_TEMPLATE_KEYS = ("Problem", "Root cause", "Durable lesson", "Prevention", "Regression")
COMMITTED_OUTPUT = [
    "output/data/benchmark_a.json",
    "output/data/benchmark_b.json",
    "output/data/benchmark_b_sfx.json",
    "output/data/benchmark_b_paddle_manga.json",
    "output/data/label_manifest.json",
    "output/data/labels_a.json",
    "output/data/recall_gt.json",
    "output/data/recall_result.json",
    "output/data/recall_ocr.json",
    "output/data/ocr_result.json",
]


def audit_claude() -> list[str]:
    p = ROOT / "CLAUDE.md"
    if not p.is_file():
        return ["CLAUDE.md 缺失"]
    n = len(p.read_text(encoding="utf-8").splitlines())
    if n > CLAUDE_MAX_LINES:
        return [f"CLAUDE.md 已达 {n} 行（阈值 {CLAUDE_MAX_LINES}）——考虑把稳定规则晋升为测试/hook，而不是继续加文"]
    return []


def audit_lessons() -> list[str]:
    p = ROOT / "docs" / "lessons.md"
    if not p.is_file():
        return ["docs/lessons.md 缺失"]
    txt = p.read_text(encoding="utf-8")
    lessons = [seg for seg in txt.split("## ") if seg.strip() and not seg.startswith("模板")]
    bad = []
    for seg in lessons:
        head = seg.splitlines()[0]
        # 跳过非 lesson 段（H1 标题/引言块）
        if head.startswith(("# ", ">")) or not head.startswith("L"):
            continue
        missing = [k for k in LESSON_TEMPLATE_KEYS if f"**{k}**" not in seg]
        if missing:
            bad.append(f"Lesson `{head}` 缺小节: {missing}")
    return bad


def audit_decisions() -> list[str]:
    d = ROOT / "docs" / "decisions"
    if not d.is_dir() or not (d / "README.md").is_file():
        return ["docs/decisions/ 缺少 README.md 索引"]
    return []


def audit_output_json() -> list[str]:
    bad = []
    for rel in COMMITTED_OUTPUT:
        p = ROOT / rel
        if not p.is_file():
            continue
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            bad.append(f"{rel} 不是合法 JSON: {e}")
    return bad


def audit_gitignore_leak() -> list[str]:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "output/", "models/", "testsets/pages/"],
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        return ["无法运行 git ls-files（跳过 gitignore 泄漏检查）"]
    leaked = [ln for ln in out.splitlines() if ln and ln.strip()]
    # models/ 与 testsets/pages/ 应整体被忽略；output/ 仅白名单文件允许
    bad = []
    for ln in leaked:
        if ln.startswith(("models/", "testsets/pages/")):
            bad.append(f"被忽略路径意外入库: {ln}")
    return bad


# ---- 文档卫生检查（2026-08-27，仓库卫生整改后加入）----


def check_workspace_empties(ws_root: Path) -> tuple[int, list[str]]:
    """workspace/ 下 artifacts 为空的 ws-* 空壳目录（work_dir() 每次调用残留的 state 骨架）。

    判据：ws-* 目录存在但其 artifacts/ 内无任何文件 → 无真实产物，可清理。
    """
    if not ws_root.is_dir():
        return 0, []
    empties: list[str] = []
    for p in ws_root.glob("ws-*"):
        if not p.is_dir():
            continue
        art = p / "artifacts"
        has_files = any(art.rglob("*")) if art.is_dir() else False
        if not has_files:
            empties.append(str(p))
    return len(empties), empties


# 不该被任何扫描进去的目录（生成物 / 缓存 / 巨量噪声）。
# 2026-09-10 接线时实测：find_duplicate_files 扫到了 output/ 下的临时残留
# （a.md/b.md 各 5 份），把噪声当成了「重复文件」发现项。
SCAN_EXCLUDE_DIRS = (
    ".git", ".venv", ".worktrees", "output", "workspace", "models",
    "node_modules", ".pytest_cache", ".ruff_cache", "__pycache__",
    ".mypy_cache", "reference", "testsets",
)

# 归档目录：**归档时复制一份正是归档的语义**，所以这里的重复不算「事实源分裂」。
# 历史归档已清理（2026-09-11）：docs/archive/ 与 docs/superpowers/ 已删除
# 2026-08-27-front3-stages-v2.md —— 那是归档快照，不是重复维护。
ARCHIVE_DIRS = ("archive", )

# 仓库根**本该有**的文件/目录：它们不是「散落」，是项目本体。
# 第一版白名单只列了几个目录，结果把 .gitignore/.mcp.json/AGENTS.md 等
# 全部举报为散落文件（20 条误报）。一个动辄误报的门禁，第二天就会被人关掉。
ROOT_ALLOWED = (
    ".gitignore", ".gitattributes", ".mcp.json", ".editorconfig",
    "AGENTS.md", "CLAUDE.md", "CLAUDE.local.md", "AGENTS.local.md",
    "README.md", "RUNBOOK.md", "pyproject.toml", "pyrightconfig.json",
    "uv.lock", "package.json", "auth_rules.json", "prompt.md",
    "loop_state.json", "ralph.ps1", "run.ps1",
    "research", "reference", ".firecrawl", ".remember", ".agent-teams",
    ".dsh", ".claude", ".githooks", "context", "data", "docs", "examples",
    "models", "output", "scripts", "src", "tests", "testsets", "tools",
    "workspace", ".venv", ".pytest_cache", ".ruff_cache", ".worktrees",
)


def find_duplicate_files(root: Path, exts=(".md",)) -> list[list[Path]]:
    """按 (文件名, 大小, 内容前 500 字) 找重复文件（跨 research/docs 等目录）。"""
    from collections import defaultdict

    groups: dict[tuple, list[Path]] = defaultdict(list)
    # 排除只看相对扫描根的路径组件：根自身位于 .worktrees 下（git worktree
    # 开发）时，绝对路径组件判定会把整个扫描误杀为空（2026-08-30 修）。
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in exts:
            continue
        parts = p.relative_to(root).parts
        if any(name in parts for name in SCAN_EXCLUDE_DIRS):
            continue
        if any(name in parts for name in ARCHIVE_DIRS):
            continue
        try:
            key = (p.stat().st_size,
                   p.read_text(encoding="utf-8", errors="ignore")[:500])
        except OSError:
            continue
        groups[key].append(p)
    return [ps for ps in groups.values() if len(ps) > 1]


def check_top_level_clutter(root: Path, allowed: tuple[str, ...] = ROOT_ALLOWED) -> list[str]:
    """顶层不应有的散落文件（白名单外且不是目录的条目）。"""
    if not root.is_dir():
        return []
    stray = [str(p) for p in root.iterdir()
             if p.is_file() and p.name not in allowed and not p.name.startswith(".env")]
    return stray


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="amta Harness 熵审计")
    ap.add_argument(
        "--strict", action="store_true",
        help="门禁模式：有发现即 exit 1（供 fastcheck 调用）；默认咨询模式恒 exit 0",
    )
    args = ap.parse_args(argv)

    findings: list[str] = []
    findings += audit_claude()
    findings += audit_lessons()
    findings += audit_decisions()
    findings += audit_output_json()
    findings += audit_gitignore_leak()

    # 文档卫生（2026-08-27）
    n_ws, ws_paths = check_workspace_empties(ROOT / "workspace")
    if n_ws:
        findings.append(f"workspace/ 空壳 ws-* 目录: {n_ws} 个（artifacts 无文件，建议清理）")
        for p in ws_paths[:5]:
            findings.append(f"    {Path(p).name}")
    dups = find_duplicate_files(ROOT)
    if dups:
        findings.append(f"重复文件: {len(dups)} 组（同名同内容，建议只留单一事实源）")
        for g in dups[:5]:
            findings.append(f"    {' / '.join(Path(x).name for x in g)}")
    stray = check_top_level_clutter(ROOT)
    if stray:
        findings.append(f"顶层散落文件: {len(stray)} 个（应归位 / 删除）")
        for s in stray[:5]:
            findings.append(f"    {Path(s).name}")

    if findings:
        tag = "门禁失败" if args.strict else "建议项，非门禁"
        print(f"== [audit] 发现（{tag}）==")
        for f in findings:
            print(f"  - {f}")
        return 1 if args.strict else 0

    print("== [audit] 未发现 Harness 熵 ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
