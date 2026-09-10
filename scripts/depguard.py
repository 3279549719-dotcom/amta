"""depguard — 依赖膨胀守卫（vibe-check-mcp 的机械落点，ADR-015）。

在"引入第三方依赖"这个动作发生前/后做确定性拦截与审计，等价于 vibe-check-mcp
在 AI 准备引入第三方库解决小任务时喊停："能否用原生/标准库实现？"

扫描范围：src/ scripts/ tests/ 里的顶层第三方 import（stdlib / 本仓模块除外）。
三档判定：
  1. **未声明**（undeclared）：代码 import 了第三方库，但 pyproject.toml [project].dependencies 没声明
     → 拦截。要么补声明（并审视是否真需要），要么改用标准库。
  2. **已声明未使用**（unused）：pyproject 声明了，但代码里没 import → 死依赖，删除。
  3. **死传递依赖**（redundant）：锁在 venv/uv.lock，但既未直接 import 也不是任一已用库的传递依赖
     → 提醒（本脚本只报直接 import 与声明，传递链交给 uv tree 审查）。

例外（白名单，模型目录等运行时动态 import，不入 pyproject）：
  - onnx_infer        # models/baberu-ocr/ 内嵌，sys.path 动态注入
  - pytest            # 开发工具链（全局安装，非运行时依赖，ADR-004）

退出码：0 = 干净；非 0 = 有未声明/未使用依赖（建议硬门禁，接进 pre-commit/fastcheck）。
"""
from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("src", "scripts", "tests")
LOCAL_TOP = {"amta", "scripts", "tests"}  # 本仓顶层模块，不是第三方
# 分布名与 import 名的映射（import PIL → 包名 pillow）
IMPORT_TO_PKG = {"PIL": "pillow", "cv2": "opencv-python"}
# 运行时动态 import / 开发工具链白名单（不入 [project].dependencies）
ALLOWLIST = {
    "onnx_infer",  # models/baberu-ocr/ 内嵌，sys.path 动态注入
    "pytest",      # 开发工具链（全局安装，非运行时依赖，ADR-004）
    # hayai 模型权重目录（HAYAI_OCR_MODEL）内 trust_remote_code 动态加载的自定义模块，
    # 运行时 sys.path 注入（ocr_engines._get_hayai），非 PyPI 包、无从声明。
    # 消费方：src/amta/backends/ocr_engines.py + scripts/probes/ q3 系列探针。
    "modeling_hayai",
}
# 实验脚本排除（A/B 测试 / 调研用，等正式集成主流水线再补依赖声明）
EXCLUDE_FILES = {
    "scripts/detect_rtdetr.py",
    "scripts/run_detect_ab.py",
    "scripts/gen_detect_ab_report.py",
    "tests/test_detect_rtdetr.py",
    "scripts/ctd_detector.py",
    "scripts/detectors.py",
    "scripts/run_detect_multi.py",
    "scripts/gen_detect_multi_report.py",
    "tests/test_detect_ctd.py",
    "scripts/probes/_probe_hayai_confidence.py",
    "scripts/probes/_probe_confidence_compare.py",
}


def _is_local_module(top: str) -> bool:
    """top 是否对应本仓内某个脚本/测试文件（tests/scripts 常互 import，是本地模块不是第三方）。"""
    for sub in SCAN_DIRS:
        if (ROOT / sub / f"{top}.py").is_file():
            return True
    # scripts/probes/ 归档探针：ruff/pyright 已 exclude，但被 tests 引用时仍是本地模块（非第三方）
    return bool((ROOT / "scripts" / "probes" / f"{top}.py").is_file())


def _norm(name: str) -> str:
    """分布名比较键归一化（PEP 503）：大小写不敏感，'-'/'_'/'.' 等价。

    import 顶层名与 pyproject 分布名常只差分隔符（如 hayai_ocr vs hayai-ocr），
    直接比较必然误报"未声明"+"未使用"双杀；比较键统一成小写连字符形。
    注意只用于比较，界面文案仍显示原始名。
    """
    return name.lower().replace("_", "-").replace(".", "-")


def _declared_deps() -> set[str]:
    pyproject = ROOT / "pyproject.toml"
    if not pyproject.is_file():
        return set()
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    proj = data.get("project", {})
    deps = proj.get("dependencies", [])
    names = set()
    for d in deps:
        # 形如 "requests==2.34.2" / "pillow>=10"
        name = d.strip().split(">=")[0].split("==")[0].split("<")[0].strip()
        names.add(name.lower())
    return names


def _scan_third_party() -> dict[str, set[str]]:
    """返回 {文件相对路径: {第三方顶层模块名}}。"""
    found: dict[str, set[str]] = {}
    for top in SCAN_DIRS:
        base = ROOT / top
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            rel = str(p.relative_to(ROOT)).replace("\\", "/")
            # archive/ = 归档代码（ruff/pyright 已排除），不参与依赖治理
            if rel.startswith(("scripts/archive/", "tests/archive/")):
                continue
            if rel in EXCLUDE_FILES:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            third = set()
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    # 只查绝对导入的顶层第三方；相对导入（level>0，如 orchestrator 包内
                    # from .context import）是本仓子模块，ast 会把点号剥进 node.level、
                    # node.module 只剩子模块名，误判为第三方，须跳过。
                    mods = [node.module.split(".")[0]]
                for m in mods:
                    if m in LOCAL_TOP or m == "__future__":
                        continue
                    if m in sys.stdlib_module_names:
                        continue
                    if m in ALLOWLIST:
                        continue
                    if _is_local_module(m):
                        continue
                    third.add(m)
            if third:
                found[str(p.relative_to(ROOT))] = third
    return found


def main() -> int:
    declared = _declared_deps()
    declared_keys = {_norm(d) for d in declared}
    found = _scan_third_party()
    used: set[str] = set()
    issues: list[str] = []
    for rel, mods in sorted(found.items()):
        for m in sorted(mods):
            pkg = IMPORT_TO_PKG.get(m, m)
            key = _norm(pkg)
            used.add(key)
            if key not in declared_keys:
                issues.append(f"[未声明] {rel}: import {m} 未在 [project].dependencies 声明")

    # 声明了但没被任何 import 用到
    for d in sorted(declared):
        if _norm(d) not in used:
            issues.append(f"[未使用] pyproject 声明 {d}，但 src/scripts/tests 未 import 到 —— 死依赖，删除")

    if issues:
        print("== [depguard] 依赖膨胀检查：发现问题 ==")
        for i in issues:
            print(f"  - {i}")
        print("== 提示：加依赖前先自问『能否用原生/标准库实现？』（ADR-015）；")
        print("   确认需要再进 pyproject.toml，并用 `uv run uv lock` + `uv tree` 复核传递链。 ==")
        return 1

    print("== [depguard] 依赖干净：所有第三方 import 均已声明且在使用中 ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
