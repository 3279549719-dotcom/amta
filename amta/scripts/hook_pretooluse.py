"""
Claude Code PreToolUse hook: git commit/merge 前自动跑快速 fastcheck。

只拦截包含 "git commit" 或 "git merge" 的 Bash 工具调用。
快速 fastcheck = compile + ruff + pyright（不跑 pytest，hook 有 30s 超时）。
FAIL 则输出 {"decision": "block", "continueOnBlock": true, "reason": "..."} 阻止提交。

Claude Code ≥2.1.210 语义变化：PreToolUse deny 默认=整个回合结束（reason 只作 chat 警告），agent 无法修了重试，
对 ralph 无头驱动尤其致命。continueOnBlock:true 让 reason 作为工具错误回给模型 → agent 修掉再提交。
无头 claude -p 下被 block 的 commit 若不带 continueOnBlock，回合静默终止、本次迭代白跑。

配置：.claude/settings.json -> hooks.PreToolUse -> command: "py -3.13 scripts/hook_pretooluse.py"
"""
import sys
import json
import subprocess


def main():
    # 从 stdin 读取工具调用信息
    try:
        data = json.load(sys.stdin)
    except Exception:
        # 读不到 stdin 就放行
        print(json.dumps({"decision": "allow"}))
        return

    tool_input = data.get("tool_input", {})
    if isinstance(tool_input, dict):
        command = tool_input.get("command", "")
    else:
        command = str(tool_input)

    # 只拦截 git commit / git merge
    is_git_commit = "git commit" in command or "git merge" in command
    if not is_git_commit:
        print(json.dumps({"decision": "allow"}))
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
            # continueOnBlock=true：把 reason 作为工具错误回给模型（≥2.1.210 默认是结束回合，agent 没机会修了重试）
            print(json.dumps({"decision": "block", "continueOnBlock": True, "reason": reason}))
            return

    print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
