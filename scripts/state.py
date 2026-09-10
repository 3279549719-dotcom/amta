"""state — StateManager 的 CLI 入口（Embedded 模式）。

对话开始：uv run python scripts/state.py bootstrap
对话结束：uv run python scripts/state.py finish "feat: 做了什么"

finish **不是**裸 commit：它先跑完整质检（fastcheck 全量 8 步，含 pytest），
红了拒绝落盘、改动原样留在工作区。这是"对话结束"这个收口点的强制门——
2026-09-10 事故的根因就是唯一的拦截层只跑了 --quick 却按整扇门记账。

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

from amta.common.state_manager import QualityGateFailed, StateManager, finish_verified


def main() -> int:
    ap = argparse.ArgumentParser(description="amta 对话状态管理（bootstrap + finish）")
    sub = ap.add_subparsers(dest="command", required=True)

    # bootstrap
    p_boot = sub.add_parser("bootstrap", help="对话开始：读取 git + env 状态，输出统一格式的状态摘要")
    p_boot.add_argument("--no-env", action="store_true", help="跳过环境自检")
    p_boot.set_defaults(func=_cmd_bootstrap)

    # finish
    p_fin = sub.add_parser("finish", help="对话结束：先跑完整质检，通过后 git add + commit")
    p_fin.add_argument("summary", nargs="?", default=None, help="commit message（不能为空）")
    p_fin.add_argument(
        "--message-file", type=Path, default=None,
        help="从文件读 commit message（多行/含引号时用，绕开 shell 引号地狱）",
    )
    p_fin.add_argument("--tag", default=None, help="打 tag（里程碑用）")
    p_fin.add_argument(
        "--skip-check", action="store_true",
        help="逃生门：跳过完整质检直接提交（默认不跳；用了会在输出里留痕）",
    )
    p_fin.set_defaults(func=_cmd_finish)

    args = ap.parse_args()
    return args.func(args)


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    sm = StateManager()
    snap = sm.bootstrap(env_check=not args.no_env)
    print(str(snap))
    return 0


def _cmd_finish(args: argparse.Namespace) -> int:
    # --message-file 优先：Windows PowerShell 会把多行 message 里的引号当参数分隔符，
    # 把一条 message 拆成十几个 argv（实测），文件传递绕开这条路。
    if args.message_file is not None:
        summary = args.message_file.read_text(encoding="utf-8")
    else:
        summary = args.summary

    if not summary or not summary.strip():
        print("ERROR: 必须提供 summary（positional 或 --message-file）", file=sys.stderr)
        return 1

    if args.skip_check:
        print("[state] !! --skip-check：跳过完整质检直接提交（这次没有门）", file=sys.stderr)
    try:
        finish_verified(summary, tag=args.tag, skip_check=args.skip_check)
    except QualityGateFailed as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"[state] finish OK: {summary.strip().splitlines()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
