"""memory_recent — 时效状态（上次停在哪、最近改了什么）。

用法: python scripts/memory_recent.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_stdout = cast(Any, sys.stdout)
if hasattr(_stdout, "reconfigure"):
    _stdout.reconfigure(encoding="utf-8", errors="replace")

from amta.memory.estate import estate_root  # noqa: E402
from amta.memory.tools import do_recent  # noqa: E402


def main() -> int:
    print(do_recent(estate_root()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
