"""memory_grep — 知识地产内容检索。

用法: python scripts/memory_grep.py --query <关键词|正则> [--scope lessons|decisions|remember|research|all] [--limit N]
返回: 每命中条目一行 `ID|标题|路径:行范围|命中行`（每条目只报首个命中，不给全文）。
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
from amta.memory.tools import _fmt, do_grep  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="知识地产内容检索")
    ap.add_argument("--query", required=True, help="关键词或正则")
    ap.add_argument("--scope", default="all", choices=["lessons", "decisions", "remember", "research", "all"])
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    hits = do_grep(estate_root(), query=a.query, scope=a.scope, limit=a.limit)
    if not hits:
        print(f"[memory_grep] 无命中：{a.query!r}（scope={a.scope}）——换个关键词，或 memory_index 看清单")
        return 0
    for h in hits:
        print(_fmt(h))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
