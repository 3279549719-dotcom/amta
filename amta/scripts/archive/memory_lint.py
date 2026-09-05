"""memory_lint — 记忆机制门禁（--strict：任一 FAIL 退出码 1，fastcheck 用）。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_stdout = cast(Any, sys.stdout)
if hasattr(_stdout, "reconfigure"):
    _stdout.reconfigure(encoding="utf-8", errors="replace")

from amta.memory.estate import estate_root  # noqa: E402
from amta.memory.lint import run_checks  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="记忆机制检查（CI 门禁）")
    ap.add_argument("--strict", action="store_true", help="FAIL → 退出码 1")
    a = ap.parse_args()
    findings = run_checks(estate_root())
    for f in findings:
        print(f"[{f.level}] {f.rule}: {f.msg}")
    fails = [f for f in findings if f.level == "FAIL"]
    if a.strict and fails:
        print(f"[memory_lint] strict: {len(fails)} FAIL")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
