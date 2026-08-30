"""memory_status — 记忆活性自检（与 memory_lint 同引擎；FAIL 不影响退出码，给 agent 看）。"""
from __future__ import annotations

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
    findings = run_checks(estate_root())
    for f in findings:
        print(f"[{f.level}] {f.rule}: {f.msg}")
    n_fail = sum(1 for f in findings if f.level == "FAIL")
    print(f"[memory_status] {n_fail} FAIL / {sum(1 for f in findings if f.level == 'WARN')} WARN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
