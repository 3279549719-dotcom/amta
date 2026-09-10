"""state — StateManager 的 CLI 入口（Embedded 模式）。

对话开始：uv run python scripts/state.py bootstrap
对话结束：uv run python scripts/state.py finish "feat: 做了什么"

设计原则：
- 不是"告诉 AI 去跑 git log"，是"调用一个命令就拿到所有状态"
- 状态格式统一，AI 不需要解析多种输出
- 不写文档，不写 progress.md，所有状态都在 git 里
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.common.state_manager import StateManager


def main() -> int:
    ap = argparse.ArgumentParser(description="amta 对话状态管理（bootstrap + finish）")
    sub = ap.add_subparsers(dest="command", required=True)

    # bootstrap
    p_boot = sub.add_parser("bootstrap", help="对话开始：读取 git + env 状态，输出统一格式的状态摘要")
    p_boot.add_argument("--no-env", action="store_true", help="跳过环境自检")
    p_boot.set_defaults(func=_cmd_bootstrap)

    # finish
    p_fin = sub.add_parser("finish", help="对话结束：git add + git commit")
    p_fin.add_argument("summary", help="commit message（不能为空）")
    p_fin.add_argument("--tag", default=None, help="打 tag（里程碑用）")
    p_fin.set_defaults(func=_cmd_finish)

    args = ap.parse_args()
    return args.func(args)


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    sm = StateManager()
    snap = sm.bootstrap(env_check=not args.no_env)
    print(str(snap))
    return 0


def _cmd_finish(args: argparse.Namespace) -> int:
    sm = StateManager()
    try:
        sm.finish(args.summary, tag=args.tag)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"[state] finish OK: {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
