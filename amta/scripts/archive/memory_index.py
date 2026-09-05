"""memory_index — 知识地产清单（有什么可查）。

用法: python scripts/memory_index.py [--type lessons|decisions|remember|all]
返回: 每条一行 `ID|标题|路径`。generated-from-reality，永不与地产漂移。
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
from amta.memory.tools import do_index  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="知识地产清单")
    ap.add_argument("--type", dest="type_", default="all", choices=["lessons", "decisions", "remember", "all"])
    a = ap.parse_args()
    print(do_index(estate_root(), type_=a.type_))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
