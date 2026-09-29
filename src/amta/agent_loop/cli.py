"""CLI for creating, executing, inspecting and accepting improvement tasks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import accept, create, resume, run
from .state import read


def main() -> int:
    parser = argparse.ArgumentParser(description="AMTA persistent local agent")
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("create", "run", "status", "resume", "accept"):
        sub = commands.add_parser(action)
        sub.add_argument("--task-dir", type=Path, required=True)
        if action == "create":
            sub.add_argument("--config", type=Path, required=True)
        if action == "resume":
            sub.add_argument("--feedback", required=True)
    args = parser.parse_args()
    try:
        if args.action == "create":
            state = create(args.task_dir, read(args.config))
        elif args.action == "run":
            state = run(args.task_dir)
        elif args.action == "resume":
            resume(args.task_dir, args.feedback)
            state = run(args.task_dir)
        elif args.action == "accept":
            state = accept(args.task_dir)
        else:
            state = read(args.task_dir / "task.json")
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 1 if state["status"] in ("failed", "budget_exhausted", "interrupted") else 0
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
