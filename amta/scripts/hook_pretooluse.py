"""
Claude Code PreToolUse hook: git commit/merge 前自动跑快速 fastcheck。

只拦截包含 "git commit" 或 "git merge" 的 Bash 工具调用（settings 已加 matcher: Bash，
只对 Bash 触发——Read/Grep/Edit 等不再被打扰）。
快速 fastcheck = compile + ruff + pyright（不跑 pytest，hook 有 30s 超时）。
FAIL 则输出 deny + permissionDecisionReason 阻止提交。

输出 schema（claude >=2.1.220 强制，2026-09-05 实证）：
PreToolUse 必须用 hookSpecificOutput 包装，decision 在 permissionDecision 字段：
  allow: {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
  deny:  {"hookSpecificOutput": {"hookEventName": "PreToolUse",
          "permissionDecision": "deny", "permissionDecisionReason": "..."}}
legacy 根级 {"decision":...} 在 2.1.220 被 Ajv 严格校验拒绝（(root): Invalid input）——
allow 分支变报错噪音、deny 分支完全不生效（guard 静默失效，fastcheck FAIL 的 commit 拦不住）。

配置：.claude/settings.json -> hooks.PreToolUse -> { matcher: "Bash", hooks: [command: py -3.13 scripts/hook_pretooluse.py] }
"""
import json
import subprocess
import sys


def _out(decision: str, reason: str = "") -> None:
    """按 2.1.220 hookSpecificOutput schema 输出 PreToolUse 决策。"""
    payload = {"hookEventName": "PreToolUse", "permissionDecision": decision}
    if reason:
        payload["permissionDecisionReason"] = reason
    print(json.dumps({"hookSpecificOutput": payload}))


def main():
    # 从 stdin 读取工具调用信息
    try:
        data = json.load(sys.stdin)
    except Exception:
        # 读不到 stdin 就放行
        _out("allow")
        return

    tool_input = data.get("tool_input", {})
    if isinstance(tool_input, dict):
        command = tool_input.get("command", "")
    else:
        command = str(tool_input)

    # 只拦截 git commit / git merge
    is_git_commit = "git commit" in command or "git merge" in command
    if not is_git_commit:
        _out("allow")
        return

    # 跑快速 fastcheck：compile + ruff + pyright
    checks = [
        (["py", "-3.13", "-m", "compileall", "-q", "src", "scripts"], "compile"),
        (["py", "-3.13", "-m", "ruff", "check", "src", "scripts", "tests"], "ruff"),
        (["py", "-3.13", "-m", "pyright", "src"], "pyright"),
    ]

    for cmd, name in checks:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "")[-500:]
            reason = f"[PreToolUse hook] fastcheck '{name}' failed — fix before commit/merge.\n{tail}"
            _out("deny", reason)
            return

    _out("allow")


if __name__ == "__main__":
    main()
