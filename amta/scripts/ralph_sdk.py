"""
ralph_sdk.py — Ralph Loop v5 薄壳（Claude Agent SDK 版）

设计原则（用户拍板）：
- 信息传递：宿主下达指令 → claude 执行；claude 遇决策点 → 问宿主 → 宿主回答 → 继续。
- 过程观测：claude 每一步在干嘛，实时打印。
- 权限模型（门卫，不硬编码动作）：claude 每次想动工具都过 can_use_tool 闸门。
    1) 危险黑名单（内置 + auth_rules.json deny）→ 永远拦下
    2) 只读操作 → 自动放行
    3) 宿主已授权清单（auth_rules.json allow，运行时长）→ 放行
    4) 其余写操作 → 问人
  授权清单不是代码写死的：宿主（我）在用户拍板后写入 auth_rules.json，claude 自主决定怎么执行。

跑法：
  uv run python scripts/ralph_sdk.py "指令..."
  uv run python scripts/ralph_sdk.py --file mission.txt

交互通道（DECISION_CHANNEL 环境变量）：
  terminal（默认）— 直接终端提问（人坐在电脑前时）
  file          — 写 decision_request.json 等宿主注入（人不在屏前，我转达）
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

MODEL = "deepseek-v4-flash"  # 本机端点模型，必须显式指定（SDK 默认校验会失败）
CWD = r"E:\manga translator agent\amta"
AUTH_FILE = Path(CWD) / "auth_rules.json"

# ── 内置危险黑名单：永远拦下，不落入授权/问人 ──────────────────────
ALWAYS_DENY = [
    "rm -rf", "rm -fr", "del /s", "remove-item -recurse -force",
    "git push --force", "git push -f", "git reset --hard",
    "git clean -fdx", "git checkout --", "git revert --no-commit",
    "format c:", "diskpart", "shutdown", "taskkill /f",
    "git branch -d origin", "git push --delete origin/main",
]

# ── 只读工具自动放行 ───────────────────────────────────────────────
AUTO_ALLOW_TOOLS = {"Read", "Glob", "Grep", "WebSearch", "WebFetch", "Bash"}
GIT_READONLY_PREFIXES = (
    "git status", "git log", "git show", "git diff", "git merge-base",
    "git rev-parse", "git rev-list", "git ls-tree", "git remote -v",
    "git config --get", "git tag -l", "git stash list", "git fsck",
)
# git branch 变体：裸分支/列分支只读；带写标志（删/改）非只读
GIT_BRANCH_READONLY_FLAGS = ("-a", "-r", "-v", "--list", "--merged", "--no-merged", "--show-current")


def _is_readonly_bash(command: str) -> bool:
    c = command.strip().lower()
    if c.startswith("git branch"):
        rest = c[len("git branch"):].strip()
        if rest == "":
            return True
        if rest.startswith("-") and not rest[1:2].isdigit():
            # 只有纯只读 flag 组合才算只读（-vv/-av 等），-d/-D/-m/-f 等写标志落入授权
            for flag in GIT_BRANCH_READONLY_FLAGS:
                if rest == flag or rest.startswith(flag + " ") or rest.startswith(flag + "-"):
                    return True
        return False
    return any(c.startswith(p) for p in GIT_READONLY_PREFIXES)


# ── 运行时授权清单（宿主写入，实时生效） ────────────────────────────
def load_auth_rules() -> dict:
    if AUTH_FILE.exists():
        try:
            return json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"allow": [], "deny": []}


def _hit(pattern: str, command: str) -> bool:
    return pattern.lower() in command.lower()


def check_bash(command: str) -> tuple[str, str]:
    """返回 (verdict, reason)；verdict ∈ deny / allow / ask"""
    c = command.strip().lower()
    rules = load_auth_rules()
    for pat in ALWAYS_DENY + rules.get("deny", []):
        if _hit(pat, c):
            return "deny", pat
    if _is_readonly_bash(c):
        return "allow", "只读"
    for pat in rules.get("allow", []):
        if _hit(pat, c):
            return "allow", f"已授权: {pat}"
    return "ask", ""


async def ask_host_blocking(kind: str, payload: dict) -> dict:
    """统一问人通道：kind=question（AskUserQuestion）/ approval（工具放行）。

    DECISION_CHANNEL=file：写 decision_request.json，轮询 decision_answers.json。
    """
    channel = os.environ.get("DECISION_CHANNEL", "terminal")
    if channel == "file":
        req = Path(CWD) / "decision_request.json"
        req.write_text(json.dumps({"kind": kind, **payload}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[⏸ {kind} 请求已写入 {req} — 等待宿主注入]")
        answers_file = Path(CWD) / "decision_answers.json"
        while True:
            if answers_file.exists():
                data = json.loads(answers_file.read_text(encoding="utf-8"))
                answers_file.unlink()
                req.unlink(missing_ok=True)
                return data
            await asyncio.sleep(2)

    # 终端交互
    if kind == "question":
        answers = {}
        for q in payload.get("questions", []):
            qtext = q.get("question", "")
            header = q.get("header", "")
            opts = q.get("options", [])
            multi = q.get("multiSelect", False)
            print(f"\n❓ [{header}] {qtext}")
            for i, o in enumerate(opts):
                print(f"   [{i}] {o.get('label')} — {o.get('description', '')}")
            while True:
                raw = input(f"你的选择 (0-{len(opts)-1}, 直接输入文字可自定义) > ").strip()
                if not raw:
                    raw = "0"
                if raw.isdigit() and 0 <= int(raw) < len(opts):
                    pick = opts[int(raw)].get("label")
                else:
                    pick = raw
                answers[qtext] = [pick] if multi else pick
                break
        return {"answers": answers}
    else:  # approval
        print(f"\n🛂 {payload.get('prompt', '')}")
        if payload.get("detail"):
            print(f"   {payload['detail'][:300]}")
        ok = input("  允许吗? (y/N) > ").strip().lower()
        return {"approved": ok in ("y", "yes"), "message": "宿主批准" if ok in ("y", "yes") else "宿主拒绝"}


async def handle_tool_request(tool_name: str, input_data: dict, context: ToolPermissionContext):
    """门卫：AskUserQuestion=问人；只读=放行；黑名单=拦；授权清单=放行；其余=问人。"""
    if tool_name == "AskUserQuestion":
        questions = input_data.get("questions", [])
        resp = await ask_host_blocking("question", {"questions": questions})
        return PermissionResultAllow(
            updated_input={"questions": questions, "answers": resp.get("answers", {})}
        )

    if tool_name == "Bash":
        command = input_data.get("command", "")
        print(f"\n🐚 Bash: {command[:200]}")
        verdict, reason = check_bash(command)
        if verdict == "deny":
            print(f"   ⛔ 护栏拦截（黑名单: {reason}）")
            return PermissionResultDeny(message=f"宿主护栏拦截了这条命令（命中危险清单: {reason}）。请换安全的替代方式。")
        if verdict == "allow":
            if reason != "只读":
                print(f"   ⏩ 放行（{reason}）")
            return PermissionResultAllow(updated_input=input_data)
        # ask：问人
        resp = await ask_host_blocking("approval", {
            "prompt": f"Bash 写操作: {tool_name}",
            "detail": command[:300],
        })
        if resp.get("approved"):
            return PermissionResultAllow(updated_input=input_data)
        return PermissionResultDeny(message=resp.get("message", "宿主拒绝执行这条命令。"))

    if tool_name in ("Write", "Edit"):
        fp = str(input_data.get("file_path", "?"))
        print(f"\n✏️  {tool_name}: {fp}")
        low = fp.lower()
        # 配置/钩子/敏感区一律问人（不被 allow 清单自动放行）
        sensitive = any(s in low for s in (".git/", ".claude/", ".githooks/", "settings.json", ".mcp.json"))
        if sensitive:
            resp = await ask_host_blocking("approval", {
                "prompt": f"修改敏感文件: {fp}",
                "detail": "该路径涉及配置/钩子/仓库内部，需要人工确认。",
            })
            if not resp.get("approved"):
                return PermissionResultDeny(message=resp.get("message", "宿主拒绝修改该文件。"))
            return PermissionResultAllow(updated_input=input_data)
        resp = await ask_host_blocking("approval", {
            "prompt": f"文件写操作: {fp}",
        })
        if resp.get("approved"):
            return PermissionResultAllow(updated_input=input_data)
        return PermissionResultDeny(message=resp.get("message", "宿主拒绝这次文件修改。"))

    # 其余工具放行（打印可见）
    print(f"\n🔧 {tool_name}: {str(input_data)[:200]}")
    return PermissionResultAllow(updated_input=input_data)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Ralph Loop v5 SDK 薄壳")
    parser.add_argument("prompt", nargs="?", help="任务指令（缺省则交互输入）")
    parser.add_argument("--file", help="从文件读取任务指令")
    args = parser.parse_args()

    if args.file:
        prompt = Path(args.file).read_text(encoding="utf-8").strip()
    elif args.prompt:
        prompt = args.prompt.strip()
    else:
        prompt = input("任务指令 > ").strip()
    if not prompt:
        print("没有指令，退出。")
        return 1

    print(f"\n═══ 启动 claude（{MODEL}）═══")
    options = ClaudeAgentOptions(
        cwd=CWD,
        model=MODEL,
        can_use_tool=handle_tool_request,
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.connect()
        await client.query(prompt)

        async for msg in client.receive_response():
            if isinstance(msg, ResultMessage):
                print("\n═══ 收尾 ═══")
                print(f"状态: {'✅ success' if not msg.is_error else '❌ error'}  "
                      f"reason={msg.terminal_reason!r}")
                print(f"结果: {str(msg.result)[:500]}")
                return 0 if not msg.is_error else 2
            elif isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        print(f"\n🔧 [工具调用] {block.name}")
                        print(f"  输入: {str(block.input)[:300]}")
                    elif isinstance(block, TextBlock):
                        if block.text.strip():
                            print(f"\n🤖 claude: {block.text[:300]}")
            elif isinstance(msg, SystemMessage):
                sub = msg.subtype
                if sub == "init":
                    print(f"[会话] session_id={msg.data.get('session_id', '?')[:16]}...")
                elif sub in ("control_request", "control_response"):
                    print(f"[控制] {sub}: {str(msg.data)[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
