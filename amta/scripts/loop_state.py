"""loop_state CLI — 查看 / 更新循环状态（RALPH 会话、进程、人共用）。

用法:
  python scripts/loop_state.py show
  python scripts/loop_state.py update --field key=value [--field k2=v2 ...]
  python scripts/loop_state.py blocked --reason "需要人裁决：..."

  # mission 模式（schema v2）：plan 拆解 / 推进
  python scripts/loop_state.py plan add --id C1 --desc "..." --acceptance "..."
  python scripts/loop_state.py plan done --id C1
  python scripts/loop_state.py plan list
  python scripts/loop_state.py plan reset     # 清空重拆

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

from amta.memory.loop_state import (
    load,
    plan_add,
    plan_done,
    plan_list,
    plan_reset,
    summarize,
    update,
)


def _parse_field(field: str) -> tuple[str, str]:
    key, _, value = field.partition("=")
    return key.strip(), value.strip()


def _print_plan(root: Path) -> None:
    """打印 plan 清单（每行 [x]/[ ] C# | desc | acceptance）。"""
    state = load(root)
    plan = plan_list(state)
    if not plan:
        print("（plan 空：首轮 agent 需先把 mission 拆成 chunk）")
        return
    for c in plan:
        mark = "x" if c.get("done") else " "
        acc = c.get("acceptance") or ""
        print(f"[{mark}] {c.get('chunk_id')} | {c.get('desc')} | 验收: {acc}")


def main() -> int:
    ap = argparse.ArgumentParser(description="循环状态 CLI")
    ap.add_argument("--root", default=".", help="repo 根目录（默认当前目录）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("show", help="打印状态摘要")

    p_update = sub.add_parser("update", help="合并字段并落盘（原子替换）")
    p_update.add_argument("--field", action="append", default=[], help="key=value，可多次")

    p_blocked = sub.add_parser("blocked", help="标记需人裁决（status=BLOCKED + escalation）")
    p_blocked.add_argument("--reason", required=True, help="需要人做什么")

    p_plan = sub.add_parser("plan", help="mission 拆解清单管理（schema v2）")
    pplan = p_plan.add_subparsers(dest="plan_cmd", required=True)
    pa = pplan.add_parser("add", help="追加 chunk（done=False，幂等）")
    pa.add_argument("--id", required=True, help="chunk_id，如 C1")
    pa.add_argument("--desc", required=True, help="这个 chunk 做什么")
    pa.add_argument("--acceptance", default="", help="验收标准（可机械验证）")
    pplan.add_parser("list", help="列出 chunks")
    pd = pplan.add_parser("done", help="标记 chunk 完成")
    pd.add_argument("--id", required=True, help="chunk_id")
    pplan.add_parser("reset", help="清空 plan（推翻拆解重来）")

    args = ap.parse_args()
    root = Path(args.root)
    if args.cmd == "show":
        print(summarize(load(root)))
        return 0
    if args.cmd == "blocked":
        update(root, status="BLOCKED", escalation=args.reason)
        print(summarize(load(root)))
        return 0
    if args.cmd == "plan":
        if args.plan_cmd == "add":
            plan_add(root, args.id, args.desc, args.acceptance)
        elif args.plan_cmd == "done":
            plan_done(root, args.id)
        elif args.plan_cmd == "reset":
            plan_reset(root)
        # list 及 add/done/reset 后都回显当前 plan
        _print_plan(root)
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
