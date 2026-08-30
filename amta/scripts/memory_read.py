"""memory_read — 条目/节聚焦读取。

用法: python scripts/memory_read.py --entry L19 [--section Problem|Root cause|Durable lesson|Prevention|Regression]
      python scripts/memory_read.py --entry ADR-016
"""
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
from amta.memory.tools import do_read  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="条目聚焦读取")
    ap.add_argument("--entry", required=True, help="L19 / ADR-016 / remember 文件名")
    ap.add_argument("--section", default=None, help="仅 lessons 支持五段节名")
    a = ap.parse_args()
    print(do_read(estate_root(), entry=a.entry, section=a.section))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
