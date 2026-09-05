#!/usr/bin/env python3
"""ralph_context — Ralph Loop 的确定性上下文生成。

判断性内容（成果/遗留/经验）由 agent 写进 loop_state / lessons，
本模块只做确定性搬运：
  - preamble：把 memory_index + git_log 拼成开工注入块（agent 一睁眼就看到）
  - done-msg：从 loop_state 搬运 mission/current_step/next_action，生成 DONE commit message

被 ralph.ps1 调用（uv run python scripts/ralph_context.py <cmd>）。
零依赖（stdlib only）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MAX_LINE = 200  # DONE message 单行上限，避免 commit message 过长


def build_preamble(memory_index: str, git_log: str) -> str:
    """生成开工注入块：记忆清单 + git 脉络。

    agent 拿到这个后，扫一遍清单挑相关的用 `memory.py read <ID>` 读详情，
    不需要自己想关键词去 grep（74 条全扫，召回天然 100%）。
    """
    idx = memory_index.rstrip() or "(空)"
    log = git_log.rstrip() or "(无 git 记录)"
    return (
        "## 开工上下文（外层 ralph 自动注入，实时）\n\n"
        "### 记忆清单（lessons + ADR，扫一遍挑相关的用 `memory.py read <ID>` 读详情）\n"
        f"{idx}\n\n"
        "### 最近 git 脉络（run 边界看 `ralph: DONE` 标记）\n"
        f"{log}\n\n"
        "---\n"
    )


def _trunc(s: str, n: int = MAX_LINE) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def build_done_message(state: dict) -> str:
    """从 agent 写好的 loop_state 搬运生成 DONE commit message。

    内容（mission/成果/遗留）是 agent 判断性写的，本函数只做格式化搬运。
    """
    mission = _trunc(state.get("mission", ""))
    current = _trunc(state.get("current_step", ""))
    nxt = _trunc(state.get("next_action", ""))
    return (
        f"ralph: DONE | mission: {mission}\n\n"
        f"成果: {current}\n"
        f"遗留: {nxt}\n"
    )


def _cmd_preamble(args: argparse.Namespace) -> int:
    """CLI: preamble — 跑 memory_index + git log，输出开工注入块。"""
    root = Path(args.root).resolve() if args.root else Path.cwd()
    # memory_index
    try:
        import subprocess as _sp

        mi = _sp.run(
            [sys.executable, str(root / "scripts" / "memory.py"), "index"],
            capture_output=True, text=True, cwd=str(root), timeout=30,
        )
        memory_index = mi.stdout
    except Exception:
        memory_index = "(memory_index 调用失败)"
    # git log
    try:
        import subprocess as _sp

        gl = _sp.run(
            ["git", "log", "--oneline", "-20"],
            capture_output=True, text=True, cwd=str(root), timeout=15,
        )
        git_log = gl.stdout
    except Exception:
        git_log = "(git log 调用失败)"
    sys.stdout.write(build_preamble(memory_index, git_log))
    return 0


def _cmd_done_msg(args: argparse.Namespace) -> int:
    """CLI: done-msg — 读 loop_state.json，输出 DONE commit message。"""
    root = Path(args.root).resolve() if args.root else Path.cwd()
    state_path = root / "loop_state.json"
    if not state_path.exists():
        sys.stderr.write(f"[ralph_context] loop_state.json not found: {state_path}\n")
        return 1
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        sys.stderr.write(f"[ralph_context] failed to parse loop_state.json: {exc}\n")
        return 1
    sys.stdout.write(build_done_message(state))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ralph Loop 确定性上下文生成")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_pre = sub.add_parser("preamble", help="生成开工注入块（memory_index + git log）")
    p_pre.add_argument("--root", default=None, help="项目根目录（默认 cwd）")
    p_pre.set_defaults(func=_cmd_preamble)

    p_done = sub.add_parser("done-msg", help="读 loop_state.json 生成 DONE commit message")
    p_done.add_argument("--root", default=None, help="项目根目录（默认 cwd）")
    p_done.set_defaults(func=_cmd_done_msg)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
