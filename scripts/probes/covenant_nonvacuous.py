"""反向验证：契约的探针不是空转的。

把「修复前」的版本（git HEAD 的 package.json / depguard.py）当作输入喂给**契约自己的**
判据，探针必须变红；喂当前的则必须变绿。

若这里报 0，说明契约的探针只会永远变绿 —— 那就是散文，不是护栏。

> 判据一律 **import 契约本体**，本文件不重写任何一条规则。
> （2026-09-12：本文件初版把 H1/H3 的判据又抄了一遍 —— 那正是本项目刚治好的
> 「同一规则被复制成三份」的病，探针自己犯同一个错很讽刺，故改为直接引用。）

一次性实验脚本，按项目约定放 scripts/probes/。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import amta  # noqa: F401  # UTF-8 收口点：本脚本输出中文，不 import amta 就是乱码

from test_harness_covenant import (
    _bare_python_offenders,
    _module_level_literal_set,
)


def show(path: str) -> str:
    out = subprocess.run(
        ["git", "show", f"HEAD:{path}"], cwd=ROOT, capture_output=True, check=True
    )
    return out.stdout.decode("utf-8")


def dead_paths(source: str) -> list[str]:
    exclude = _module_level_literal_set(source, "EXCLUDE_FILES") or set()
    return sorted(p for p in exclude if not (ROOT / p).exists())


def main() -> int:
    import json

    old_bad = _bare_python_offenders(json.loads(show("package.json"))["scripts"])
    now_bad = _bare_python_offenders(
        json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
    )
    old_dead = dead_paths(show("scripts/depguard.py"))
    now_dead = dead_paths((ROOT / "scripts/depguard.py").read_text(encoding="utf-8"))

    print(f"H1 旧 package.json   -> 违规 {len(old_bad):2d} 条   {old_bad[:3]}")
    print(f"H1 当前 package.json -> 违规 {len(now_bad):2d} 条")
    print(f"H3 旧 depguard 名单  -> 死路径 {len(old_dead):2d} 条   {old_dead[:3]}")
    print(f"H3 当前 depguard     -> 死路径 {len(now_dead):2d} 条")

    ok = bool(old_bad) and bool(old_dead) and not now_bad and not now_dead
    print("\n结论:", "探针非空转 —— 对旧输入变红、对新输入变绿。" if ok else "探针是空转的，契约无效。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
