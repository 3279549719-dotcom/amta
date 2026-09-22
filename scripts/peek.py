"""peek — 看一眼这个项目现在长什么样：管线全貌 + 模块地图。

只回答 grep 回答不了的问题：registry 现在有哪些 stage、谁依赖谁、哪些是
占位/孤儿阶段、src/amta/ 怎么分。读的是当前源码，不是文档快照——
registry.py / stage 文件改了，下次跑输出自动变。

什么时候用我：
  - 接手任务，想知道 pipeline 现在有哪几个 stage、谁依赖谁、哪个是占位的
                                              → peek（无参数，默认就干这个）
  - 想知道 src/amta/ 文件夹怎么分           → peek --map

什么时候别用我：
  - 找模块/类/函数/字符串在哪                 → 用 grep（那是母语，我不跟它抢）
  - 找某次跑批产物文件、查缓存                 → 用 scripts/artifact.py
  - 看 git log / diff / env / 会话状态         → 用 scripts/state.py
  - 跑翻译管线                                 → 用 scripts/run_pipeline.py

例子:
  uv run python scripts/peek.py           # 打印当前管线全貌（默认）
  uv run python scripts/peek.py --map     # 文件夹级地图
  uv run python scripts/peek.py --index   # 生成 docs/module-map.md（维护命令）
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


def generate_module_map() -> str:
    """生成文件夹级模块地图（Markdown 格式）。"""
    lines = [
        "# AMTA 模块功能地图（自动生成）",
        "",
        "> 由 `scripts/peek.py --index` 自动生成。AI 找代码先看这个，再 grep。",
        "> 更新：`uv run python scripts/peek.py --index`",
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
    lines.append("*本文件由 peek.py 自动生成，请勿手动编辑。*")

    return "\n".join(lines)


def print_folder_map() -> None:
    """打印文件夹级地图（简洁版）。"""
    print("[peek] AMTA 文件夹地图：\n")

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
    print("  完整索引: docs/module-map.md（重新生成: peek.py --index）")
    print("  管线全貌: uv run python scripts/peek.py")



def print_pipeline_status() -> None:
    """打印当前管线全貌：import 真 registry，标出占位阶段和孤儿阶段。

    这不是文档快照——每次运行都实时读 registry.py，registry 改了输出自动变。
    占位阶段：station 是 _not_implemented 闭包（调用会报尚未实现）。
    孤儿阶段：在 JSON_STAGES 里声明了，但没有任何 stage 生产它。
    """
    from amta.orchestrator.registry import get_registry
    from amta.stores.artifacts import JSON_STAGES

    registry = get_registry()
    produced_by_stage = {spec.produces: name for name, spec in registry.items() if spec.produces}

    print("[peek] 当前管线（import 真 registry，非文档快照）：\n")
    print(f"  {'阶段':<10} {'上游':<28} {'产出':<12} 默认配置")
    print("  " + "-" * 78)

    placeholders = []
    for name, spec in registry.items():
        is_placeholder = getattr(spec.station, "__name__", "") == "_placeholder"
        if is_placeholder:
            placeholders.append(name)
        upstream = ", ".join(spec.consumes) if spec.consumes else "—"
        cfg = ", ".join(f"{k}={v}" for k, v in spec.default_config.items()) or ""
        mark = "  ⚠占位" if is_placeholder else ""
        print(f"  {name:<10} {upstream:<28} {spec.produces:<12} {cfg}{mark}")

    print()

    orphans = [s for s in JSON_STAGES if s not in produced_by_stage]
    if placeholders:
        print("  ⚠ 占位阶段（已注册但工位未接，调用会报错）：")
        for pname in placeholders:
            print(f"    - {pname}")
        print()
    if orphans:
        print("  ⚠ 孤儿阶段（在 JSON_STAGES 里声明但没有任何 stage 生产它）：")
        for o in orphans:
            print(f"    - {o}")
        print()

    print("  每个阶段的实现文件（code_files，要改某阶段就读这些）：")
    for name, spec in registry.items():
        if spec.code_files:
            files = ", ".join(spec.code_files[:6])
            extra = f"  (+{len(spec.code_files)-6})" if len(spec.code_files) > 6 else ""
            print(f"    {name}: {files}{extra}")
    print()
    print("  要找具体模块/函数：直接 grep（或读 docs/module-map.md）")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="看一眼项目现状（管线全貌 / 文件夹地图 / 模块索引）；找代码请用 grep",
    )
    ap.add_argument("--index", action="store_true", help="生成/更新 docs/module-map.md")
    ap.add_argument("--map", action="store_true", help="打印文件夹级地图")
    args = ap.parse_args()

    if args.index:
        content = generate_module_map()
        out = ROOT / "docs" / "module-map.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8", newline="\n")
        print(f"[peek] 模块索引已生成: {out} ({len(content)} 字节)")
        return 0

    if args.map:
        print_folder_map()
        return 0

    # 默认：打印管线全貌
    print_pipeline_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
