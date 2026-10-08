"""state — StateManager 的 CLI 入口（Embedded 模式）。

子命令：

  旧用法（gate+ship 一把梭，向后兼容）：
    uv run python scripts/state.py finish "说明"

  新用法（gate/ship 拆分）：
    uv run python scripts/state.py gate              # 只跑质检+基线对比，不碰 git
    uv run python scripts/state.py ship "说明"        # 只按清单提交，不跑测试
    uv run python scripts/state.py baseline            # 记一次当前红名单为基线

  改到一半想快检：uv run python scripts/fastcheck.py --quick   # 秒级只读
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.common.state_manager import (
    GitCommandFailed,
    QualityGateFailed,
    StateManager,
    finish_verified,
    run_gate,
    save_baseline,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="amta 对话状态管理")
    sub = ap.add_subparsers(dest="command", required=True)

    # finish（旧用法：gate + ship 一把梭）
    p_fin = sub.add_parser("finish", help="对话结束：先质检（对比基线），通过后 git add + commit")
    p_fin.add_argument("summary", nargs="?", default=None, help="commit message")
    p_fin.add_argument(
        "--message-file", type=Path, default=None,
        help="从文件读 commit message（多行/含引号时用）",
    )
    p_fin.add_argument("--tag", default=None, help="打 tag（里程碑用）")
    p_fin.add_argument(
        "--skip-check", action="store_true",
        help="逃生门：跳过质检直接提交（用了会留痕）",
    )
    p_fin.add_argument(
        "--dry-run", action="store_true",
        help="只看收尾清单，不跑质检、不落盘",
    )
    p_fin.set_defaults(func=_cmd_finish)

    # gate（只跑质检，不碰 git）
    p_gate = sub.add_parser("gate", help="只跑质检+基线对比，不 commit")
    p_gate.add_argument(
        "--no-pytest", action="store_true",
        help="只跑 fastcheck，不单独解析 pytest 失败列表（更快但不做基线归因）",
    )
    p_gate.set_defaults(func=_cmd_gate)

    # ship（只提交，不跑测试）
    p_ship = sub.add_parser("ship", help="只按收尾清单 git add + commit，不跑质检")
    p_ship.add_argument("summary", nargs="?", default=None, help="commit message")
    p_ship.add_argument("--tag", default=None, help="打 tag")
    p_ship.add_argument(
        "--dry-run", action="store_true",
        help="只看会提交什么，不真提交",
    )
    p_ship.set_defaults(func=_cmd_ship)

    # baseline（记一次红名单）
    p_base = sub.add_parser("baseline", help="跑一次 pytest，把当前失败列表存为基线")
    p_base.set_defaults(func=_cmd_baseline)

    args = ap.parse_args()
    return args.func(args)


def _cmd_finish(args: argparse.Namespace) -> int:
    if args.message_file is not None:
        summary = args.message_file.read_text(encoding="utf-8")
    else:
        summary = args.summary

    if not summary or not summary.strip():
        print("ERROR: 必须提供 summary", file=sys.stderr)
        return 1

    if args.skip_check:
        print("[state] !! --skip-check：跳过质检直接提交", file=sys.stderr)
    try:
        report = finish_verified(
            summary, tag=args.tag, skip_check=args.skip_check, dry_run=args.dry_run,
        )
    except QualityGateFailed as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except GitCommandFailed as e:
        print(f"ERROR: 质检已过，但落盘失败：{e}", file=sys.stderr)
        return 1

    print(report.render())
    if not report.committed:
        print(f"[state] 未落盘：{report.reason}")
        return 0
    print(f"[state] finish OK: {summary.strip().splitlines()[0]}")
    return 0


def _cmd_gate(args: argparse.Namespace) -> int:
    """gate：只跑质检，不碰 git。"""
    report = run_gate(capture_pytest=not args.no_pytest)
    print(report.render())
    return 0 if report.passed else 1


def _cmd_ship(args: argparse.Namespace) -> int:
    """ship：只按清单提交，不跑测试（假设 gate 已通过）。"""
    if not args.summary or not args.summary.strip():
        print("ERROR: ship 需要 summary", file=sys.stderr)
        return 1
    manager = StateManager()
    plan = manager.commit_plan()
    if plan.is_empty:
        print(plan.render())
        print("[state] ship: 没有需要提交的改动")
        return 0
    if args.dry_run:
        print(plan.render())
        print("[state] ship --dry-run: 不落盘")
        return 0
    try:
        report = manager.finish(args.summary.strip(), tag=args.tag)
    except GitCommandFailed as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(report.render())
    print(f"[state] ship OK: {args.summary.strip().splitlines()[0]}")
    return 0


def _cmd_baseline(args: argparse.Namespace) -> int:
    """记一次当前红名单为基线。"""
    print("[state] 跑 pytest 记录基线红名单（约 2 分钟）...")
    failing = save_baseline()
    if failing:
        print(f"[state] 基线已记录：{len(failing)} 个既有红项")
        for t in failing:
            print(f"  · {t}")
    else:
        print("[state] 基线已记录：0 个红项（当前全绿）")
    print("[state] 之后 gate 只拦不在此名单里的新红")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
