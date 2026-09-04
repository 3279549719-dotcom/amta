"""loop_state CLI — 查看 / 更新循环状态（RALPH 会话、进程、人共用）。

用法:
  python scripts/loop_state.py show
  python scripts/loop_state.py update --field key=value [--field k2=v2 ...]
  python scripts/loop_state.py blocked --reason "需要人裁决：..."

字段约定见 src/amta/memory/loop_state.py。`status=BLOCKED` 是 agent 标记
"需人裁决，循环应停止"的约定字段（ralph.ps1 检测到即退出，不再空转）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_stdout = sys.stdout
if hasattr(_stdout, "reconfigure"):
    _stdout.reconfigure(encoding="utf-8", errors="replace")

from amta.memory.loop_state import load, summarize, update  # noqa: E402


def _parse_field(field: str) -> tuple[str, str]:
    key, _, value = field.partition("=")
    return key.strip(), value.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="循环状态 CLI")
    ap.add_argument("--root", default=".", help="repo 根目录（默认当前目录）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("show", help="打印状态摘要")

    p_update = sub.add_parser("update", help="合并字段并落盘（原子替换）")
    p_update.add_argument("--field", action="append", default=[], help="key=value，可多次")

    p_blocked = sub.add_parser("blocked", help="标记需人裁决（status=BLOCKED + escalation）")
    p_blocked.add_argument("--reason", required=True, help="需要人做什么")

    args = ap.parse_args()
    root = Path(args.root)
    if args.cmd == "show":
        print(summarize(load(root)))
        return 0
    if args.cmd == "blocked":
        update(root, status="BLOCKED", escalation=args.reason)
        print(summarize(load(root)))
        return 0
    fields = {k: v for k, v in (_parse_field(f) for f in args.field) if k}
    if not fields:
        print("loop_state: 至少传一个 --field key=value", file=sys.stderr)
        return 1
    update(root, **fields)
    print(summarize(load(root)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
