#!/usr/bin/env python3
"""memory.py CLI — 逻辑在 src/amta/memory.py，见其模块文档。

用法:
  python scripts/memory.py search "拟声词" [--json]
  python scripts/memory.py read L-007
  python scripts/memory.py add --id L-015 --trigger "..." --path "docs/lessons.md#L15" --value "..."
  python scripts/memory.py stats
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.memory import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
