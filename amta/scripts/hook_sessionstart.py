"""
Claude Code SessionStart hook: 新会话自动加载项目状态。

1. 先跑 memory.py inject（更新 CLAUDE.local.md）
2. 输出当前分支、git status、最近 3 条 commit、loop_state 摘要

配置：.claude/settings.json -> hooks.SessionStart -> command: "py -3.13 scripts/hook_sessionstart.py"
"""
import subprocess
import json


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip()


def main():
    # 1. 先跑 memory_inject
    subprocess.run(
        ["uv", "run", "python", "scripts/memory.py", "inject"],
        capture_output=True,
    )

    # 2. 收集项目状态
    branch = run(["git", "branch", "--show-current"])
    status = run(["git", "status", "--short"])
    log = run(["git", "log", "--oneline", "-3"])

    # 3. loop_state 摘要
    loop_state_summary = ""
    try:
        with open("loop_state.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            mission = data.get("mission", "")[:120]
            current = data.get("current_step", "")[:120]
            nxt = data.get("next_action", "")[:120]
            verified = data.get("last_verified", "")[:120]
            loop_state_summary = (
                f"  mission: {mission}...\n"
                f"  current_step: {current}...\n"
                f"  next_action: {nxt}...\n"
                f"  last_verified: {verified}..."
            )
    except Exception:
        pass

    # 4. 输出（Claude Code 会显示给 agent）
    print("=== SessionStart: Project State ===")
    print(f"Branch: {branch}")
    print(f"\nGit status: {'(clean)' if not status else status}")
    print(f"\nRecent commits:\n{log}")
    if loop_state_summary:
        print(f"\nLoop state:\n{loop_state_summary}")
    print("====================================")


if __name__ == "__main__":
    main()
