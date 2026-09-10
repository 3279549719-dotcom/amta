"""refactor_module — 批量重命名模块导入路径（深接口工具）。

当你把一个模块从旧路径移到新路径（如子包化），AI 需要手动 grep 所有引用、
逐个改导入。这个脚本一键完成：找引用 → 改导入 → 跑相关测试。

用法:
  # 预览变更（不实际修改）
  uv run python scripts/refactor_module.py --old amta.detect_station --new amta.stations.detect --dry-run

  # 执行修改
  uv run python scripts/refactor_module.py --old amta.detect_station --new amta.stations.detect

  # 执行修改并跑 pytest
  uv run python scripts/refactor_module.py --old amta.detect_station --new amta.stations.detect --test

  # 限定搜索目录
  uv run python scripts/refactor_module.py --old amta.xxx --new amta.yyy --scope src tests
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def find_python_files(scope_dirs: list[Path]) -> list[Path]:
    """递归找所有 .py 文件。"""
    files = []
    for d in scope_dirs:
        if d.exists():
            files.extend(d.rglob("*.py"))
    return sorted(set(files))


def build_replacements(old: str, new: str) -> list[tuple[re.Pattern, str]]:
    """构建导入路径的正则替换规则。

    处理的模式：
      from amta.old_path import xxx      -> from amta.new_path import xxx
      from amta.old_path import xxx as y -> from amta.new_path import xxx as y
      import amta.old_path               -> import amta.new_path
      import amta.old_path as alias      -> import amta.new_path as alias
      from amta.old_path.xxx import yyy  -> from amta.new_path.xxx import yyy
    """
    old_escaped = re.escape(old)

    patterns = [
        # from amta.old_path(.sub)? import ...
        (re.compile(rf"from {old_escaped}(\.[\w.]+)?\s+import"),
         f"from {new}\\1 import"),
        # import amta.old_path(.sub)? (as alias)?
        (re.compile(rf"import {old_escaped}(\.[\w.]+)?(\s+as\s+\w+)?"),
         f"import {new}\\1\\2"),
    ]
    return patterns


def apply_replacements(content: str, patterns: list[tuple[re.Pattern, str]]) -> tuple[str, int]:
    """对文件内容应用所有替换规则，返回 (新内容, 替换次数)。"""
    total = 0
    for pat, repl in patterns:
        content, n = pat.subn(repl, content)
        total += n
    return content, total


def run_pytest(test_files: list[Path] | None = None) -> int:
    """跑 pytest。如果指定了测试文件，只跑那些；否则跑全量。"""
    cmd = ["uv", "run", "pytest", "-x", "-q"]
    if test_files:
        cmd.extend(str(f) for f in test_files)
    else:
        cmd.append("tests")
    print(f"\n[refactor_module] 运行: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    return result.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="批量重命名模块导入路径")
    ap.add_argument("--old", required=True, help="旧模块点路径，如 amta.detect_station")
    ap.add_argument("--new", required=True, help="新模块点路径，如 amta.stations.detect")
    ap.add_argument("--scope", nargs="+", default=["src", "tests", "scripts"],
                    help="搜索目录（默认 src tests scripts）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不实际修改")
    ap.add_argument("--test", action="store_true", help="修改后跑 pytest")
    args = ap.parse_args()

    old = args.old.strip()
    new = args.new.strip()

    if old == new:
        print("[refactor_module] 错误：old 和 new 相同")
        return 1

    scope_dirs = [ROOT / s for s in args.scope]
    files = find_python_files(scope_dirs)
    print(f"[refactor_module] 扫描 {len(files)} 个 .py 文件（scope: {args.scope}）")
    print(f"[refactor_module] 替换: {old}  ->  {new}")
    if args.dry_run:
        print("[refactor_module] *** DRY RUN 模式，不实际修改 ***")
    print()

    patterns = build_replacements(old, new)
    changed_files: list[Path] = []
    total_replacements = 0

    for fpath in files:
        try:
            content = fpath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue

        new_content, n = apply_replacements(content, patterns)
        if n > 0:
            rel = fpath.relative_to(ROOT)
            print(f"  {rel}: {n} 处替换")
            total_replacements += n
            changed_files.append(fpath)
            if not args.dry_run:
                fpath.write_text(new_content, encoding="utf-8")

    print()
    if total_replacements == 0:
        print("[refactor_module] 没有找到任何引用")
        return 0

    print(f"[refactor_module] 共修改 {len(changed_files)} 个文件，{total_replacements} 处替换")

    if args.dry_run:
        print("[refactor_module] DRY RUN 完成，未实际修改。去掉 --dry-run 执行。")
        return 0

    # 收集可能受影响的测试文件
    test_files = [f for f in changed_files if "test" in f.name.lower() or "/tests/" in str(f).replace("\\", "/")]

    if args.test:
        rc = run_pytest(test_files if test_files else None)
        if rc != 0:
            print(f"\n[refactor_module] 警告：pytest 失败（exit {rc}），请检查导入是否有遗漏")
            return rc
        print("\n[refactor_module] pytest 通过 ✓")

    print("\n[refactor_module] 完成。建议：git diff 检查变更，然后 fastcheck。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
