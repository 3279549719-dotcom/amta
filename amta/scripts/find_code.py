"""find_code — amta 代码/模块智能检索工具（深接口）。

解决的问题：AI 每次找模块功能都要 cd + grep + 翻文件，效率低。
这个工具一键搜索 src/amta/ 下所有模块的 docstring、类名、函数名，
返回匹配的文件路径 + 模块摘要 + 匹配符号。

用法:
  # 关键词搜索（功能描述/函数名/模块名都可以）
  uv run python scripts/find_code.py 翻译
  uv run python scripts/find_code.py artifact cache
  uv run python scripts/find_code.py inpaint

  # 生成/更新模块功能索引文档 docs/module-map.md
  uv run python scripts/find_code.py --index

  # 打印文件夹级地图（每个子包有什么模块）
  uv run python scripts/find_code.py --map

  # 只搜特定子包
  uv run python scripts/find_code.py 翻译 --scope translation stations
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.common.paths import ROOT as _PATHS_ROOT

ROOT = _PATHS_ROOT  # 统一用 paths.ROOT，不自己算
SRC = ROOT / "src" / "amta"

# 跳过的目录/文件
SKIP_DIRS = {"__pycache__", ".venv"}
SKIP_FILES = {"__init__.py"}  # __init__.py 单独处理


def parse_module(filepath: Path) -> dict:
    """解析一个 Python 模块，提取 docstring、类名、函数名。"""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return {"doc": "", "classes": [], "functions": [], "error": True}

    doc = ast.get_docstring(tree) or ""
    classes = []
    functions = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.col_offset == 0:
            functions.append(node.name)

    return {
        "doc": doc.strip(),
        "classes": classes,
        "functions": functions,
        "error": False,
    }


def get_module_summary(info: dict, max_len: int = 120) -> str:
    """从 docstring 提取第一行作为模块摘要。"""
    if not info["doc"]:
        return "(无 docstring)"
    first_line = info["doc"].split("\n")[0].strip()
    if len(first_line) > max_len:
        first_line = first_line[:max_len] + "..."
    return first_line


def search_keyword(keyword: str, scope_dirs: list[Path] | None = None) -> list[dict]:
    """搜索关键词，返回匹配的模块列表。"""
    results = []
    search_dirs = scope_dirs or [SRC]
    kw_lower = keyword.lower()

    for base in search_dirs:
        if not base.exists():
            continue
        for filepath in sorted(base.rglob("*.py")):
            if any(skip in filepath.parts for skip in SKIP_DIRS):
                continue

            rel = filepath.relative_to(ROOT)
            info = parse_module(filepath)

            # 搜索范围：模块路径、docstring、类名、函数名
            searchable = " ".join([
                str(rel).lower(),
                info["doc"].lower(),
                " ".join(info["classes"]).lower(),
                " ".join(info["functions"]).lower(),
            ])

            if kw_lower in searchable:
                # 找出具体匹配了什么
                matched_symbols = []
                for c in info["classes"]:
                    if kw_lower in c.lower():
                        matched_symbols.append(f"class {c}")
                for f in info["functions"]:
                    if kw_lower in f.lower():
                        matched_symbols.append(f"def {f}")
                if kw_lower in info["doc"].lower():
                    matched_symbols.append("(docstring 匹配)")
                if kw_lower in str(rel).lower():
                    matched_symbols.append("(路径匹配)")

                results.append({
                    "path": str(rel),
                    "summary": get_module_summary(info),
                    "matched": matched_symbols,
                    "classes": info["classes"],
                    "functions": info["functions"][:10],  # 最多显示10个
                })

    return results


def print_search_results(results: list[dict], keyword: str) -> None:
    """打印搜索结果。"""
    if not results:
        print(f"[find_code] 未找到匹配 '{keyword}' 的模块")
        print("[find_code] 提示：用 --map 查看所有模块，或 --index 生成完整索引")
        return

    print(f"[find_code] 关键词 '{keyword}' 匹配 {len(results)} 个模块：\n")
    for i, r in enumerate(results, 1):
        print(f"  {i}. {r['path']}")
        print(f"     摘要: {r['summary']}")
        if r["matched"]:
            print(f"     匹配: {', '.join(r['matched'])}")
        if r["classes"]:
            print(f"     类: {', '.join(r['classes'][:5])}")
        if r["functions"]:
            print(f"     函数: {', '.join(r['functions'][:5])}")
        print()


def generate_module_map() -> str:
    """生成文件夹级模块地图（Markdown 格式）。"""
    lines = [
        "# AMTA 模块功能地图（自动生成）",
        "",
        "> 由 `scripts/find_code.py --index` 自动生成。AI 找代码先看这个，再 grep。",
        "> 更新：`uv run python scripts/find_code.py --index`",
        "",
    ]

    # 按子包组织
    subpackages = sorted([d for d in SRC.iterdir() if d.is_dir() and d.name not in SKIP_DIRS])

    for subpkg in subpackages:
        pkg_name = subpkg.name
        # 读取子包的 __init__.py docstring 作为子包摘要
        init_file = subpkg / "__init__.py"
        pkg_summary = ""
        if init_file.exists():
            init_info = parse_module(init_file)
            pkg_summary = get_module_summary(init_info, 200)

        lines.append(f"## `{pkg_name}/` — {pkg_summary or '(子包)'}")
        lines.append("")

        # 列出子包下的模块
        modules = sorted([f for f in subpkg.glob("*.py") if f.name not in SKIP_FILES])
        if not modules:
            # 可能有嵌套子包
            nested = sorted([d for d in subpkg.iterdir() if d.is_dir() and d.name not in SKIP_DIRS])
            for n in nested:
                lines.append(f"- `{n.name}/` (嵌套子包)")
            lines.append("")
            continue

        for mod in modules:
            info = parse_module(mod)
            summary = get_module_summary(info, 150)
            symbols = []
            if info["classes"]:
                symbols.append(f"类: {', '.join(info['classes'][:3])}")
            if info["functions"]:
                symbols.append(f"函数: {', '.join(info['functions'][:5])}")
            sym_str = f"（{'；'.join(symbols)}）" if symbols else ""
            lines.append(f"- **`{mod.name}`** — {summary}{sym_str}")

        lines.append("")

    # 顶层模块（src/amta/ 下的 .py 文件）
    top_modules = sorted([f for f in SRC.glob("*.py") if f.name not in SKIP_FILES])
    if top_modules:
        lines.append("## `(顶层)` — src/amta/ 下的独立模块")
        lines.append("")
        for mod in top_modules:
            info = parse_module(mod)
            summary = get_module_summary(info, 150)
            lines.append(f"- **`{mod.name}`** — {summary}")
        lines.append("")

    # scripts/ 目录
    lines.append("## `scripts/` — CLI 工具入口")
    lines.append("")
    script_files = sorted([f for f in (ROOT / "scripts").glob("*.py")])
    for sf in script_files:
        info = parse_module(sf)
        summary = get_module_summary(info, 120)
        lines.append(f"- **`{sf.name}`** — {summary}")
    lines.append("")

    lines.append("---")
    lines.append("*本文件由 find_code.py 自动生成，请勿手动编辑。*")

    return "\n".join(lines)


def print_folder_map() -> None:
    """打印文件夹级地图（简洁版）。"""
    print("[find_code] AMTA 文件夹地图：\n")

    subpackages = sorted([d for d in SRC.iterdir() if d.is_dir() and d.name not in SKIP_DIRS])
    for subpkg in subpackages:
        init_file = subpkg / "__init__.py"
        pkg_summary = ""
        if init_file.exists():
            init_info = parse_module(init_file)
            pkg_summary = get_module_summary(init_info, 100)

        modules = [f.name for f in subpkg.glob("*.py") if f.name not in SKIP_FILES]
        print(f"  {subpkg}/  ({len(modules)} 模块) — {pkg_summary}")
        if modules:
            print(f"    {', '.join(modules[:8])}{'...' if len(modules) > 8 else ''}")

    print()
    print("  详细功能: uv run python scripts/find_code.py <关键词>")
    print("  完整索引: uv run python scripts/find_code.py --index")


def main() -> int:
    ap = argparse.ArgumentParser(description="amta 代码/模块智能检索工具")
    ap.add_argument("keyword", nargs="*", help="搜索关键词（功能/函数/模块名）")
    ap.add_argument("--index", action="store_true", help="生成/更新 docs/module-map.md")
    ap.add_argument("--map", action="store_true", help="打印文件夹级地图")
    ap.add_argument("--scope", nargs="+", default=None,
                    help="限定搜索子包（如 translation stations）")
    args = ap.parse_args()

    if args.index:
        content = generate_module_map()
        out = ROOT / "docs" / "module-map.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        print(f"[find_code] 模块索引已生成: {out} ({len(content)} 字节)")
        return 0

    if args.map:
        print_folder_map()
        return 0

    if not args.keyword:
        ap.print_help()
        return 1

    keyword = " ".join(args.keyword)

    scope_dirs = None
    if args.scope:
        scope_dirs = [SRC / s for s in args.scope]

    results = search_keyword(keyword, scope_dirs)
    print_search_results(results, keyword)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
