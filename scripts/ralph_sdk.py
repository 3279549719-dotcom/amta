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
from claude_agent_sdk.types import (
    HookContext,
    HookInput,
    HookJSONOutput,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

MODEL = "deepseek-v4-flash"  # 本机端点模型，必须显式指定（SDK 默认校验会失败）
CWD = r"E:\manga translator agent\amta"
AUTH_FILE = Path(CWD) / "auth_rules.json"
PROJECT_ROOT = Path(r"E:\manga translator agent").resolve()

# 敏感路径：凭据/配置/仓库内部，任何读写都需问人（铁律①：凭据永不自动交）
SENSITIVE_PATH_PARTS = (
    ".git", ".claude", ".githooks",
    "settings.json", ".mcp.json", ".env", "auth_rules.json",
)

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
                if rest == flag or rest.startswith((flag + " ", flag + "-")):
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


# ── 权限宪章门卫（PreToolUse hook，每个工具调用都过闸） ──────────────
def _is_sensitive_path(path: str) -> bool:
    if not path:
        return False
    low = path.lower().replace("\\", "/")
    return any(s in low for s in SENSITIVE_PATH_PARTS)


def _is_inside_project(path: str) -> bool:
    """项目边界：整个 E:/manga translator agent 目录树内放行，之外问人（铁律②）"""
    if not path:
        return True
    p = Path(path)
    if not p.is_absolute():
        return True  # 相对路径基于 cwd（项目内），视为项目内
    try:
        p.resolve().relative_to(PROJECT_ROOT)
        return True
    except ValueError:
        return False


def _is_git_redline(c: str) -> bool:
    """git 红线（用户拍板 Q3）：push / 删分支 / 强推 / 危险重置 → 问人"""
    if c.startswith("git push"):
        return True
    if c.startswith("git branch") and any(f in c for f in (" -d ", " -D ", "--delete", "-d ", "-D ")):
        return True
    if c.startswith(("git reset", "git clean")):
        return True
    if c.startswith(("git remote", "git tag")):
        return True
    return bool(c.startswith(("git reflog", "git gc", "git prune")))


def _is_install_cmd(c: str) -> bool:
    """依赖安装（用户拍板 Q2）：全自动放行"""
    return any(
        c.startswith(p)
        for p in (
            "pip install", "pip3 install", "uv add", "uv pip install", "uv sync",
            "npm install", "pnpm install", "yarn add", "yarn install",
            "cargo add", "go get", "poetry add",
        )
    )


def classify_tool(tool_name: str, tool_input: dict) -> tuple[str, str]:
    """门卫分类器：返回 (verdict, reason)，verdict ∈ deny / ask / allow。

    顺序：黑名单 deny → git 红线 ask → 敏感文件 ask → 项目外 ask → 其余 allow。
    """
    if tool_name == "AskUserQuestion":
        return "ask", "用户决策点（AskUserQuestion）"

    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        c = command.strip().lower()
        rules = load_auth_rules()
        for pat in ALWAYS_DENY + rules.get("deny", []):
            if _hit(pat, c):
                return "deny", f"黑名单拦截: {pat}"
        if _is_readonly_bash(c):
            return "allow", "只读命令"
        if _is_git_redline(c):
            return "ask", "git 红线（push/删分支/重置等），需人确认"
        if _is_install_cmd(c):
            return "allow", "依赖安装（已授权自动）"
        for pat in rules.get("allow", []):
            if _hit(pat, c):
                return "allow", f"授权清单: {pat}"
        # 工作区内常规命令（pytest/uv/git add/commit/merge/python 等）→ 放行
        return "allow", "项目内常规命令"

    if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        fp = str(tool_input.get("file_path", ""))
        if _is_sensitive_path(fp):
            return "ask", f"敏感文件（凭据/配置/仓库内部）: {fp}"
        if not _is_inside_project(fp):
            return "ask", f"项目外路径: {fp}"
        return "allow", "项目内写操作"

    if tool_name in ("Read",):
        fp = str(tool_input.get("file_path", ""))
        if _is_sensitive_path(fp):
            return "ask", f"敏感文件读取: {fp}"
        if not _is_inside_project(fp):
            return "ask", f"项目外路径: {fp}"
        return "allow", "只读"

    if tool_name == "Delete":
        fp = str(tool_input.get("file_path", ""))
        if _is_sensitive_path(fp):
            return "ask", f"敏感文件删除: {fp}"
        if not _is_inside_project(fp):
            return "ask", f"项目外路径: {fp}"
        return "allow", "项目内删除"

    # 其余工具（Glob/Grep/WebSearch/WebFetch/Bash 只读等）→ 放行
    return "allow", "默认放行"


async def gate_pre_tool_use(inp: HookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
    """PreToolUse 门卫：每个工具调用在权限规则评估前先过此闸。

    ask → CLI 发权限请求 → can_use_tool 回调（file 通道问人）。
    """
    tool_name = inp.get("tool_name", "")
    tool_input = inp.get("tool_input", {}) or {}
    verdict, reason = classify_tool(tool_name, tool_input)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": verdict,
            "permissionDecisionReason": reason,
        }
    }


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
    """can_use_tool：只处理被 PreToolUse hook 判为 ask 的请求（问人）。

    AskUserQuestion → 转达 questions、注入 answers；其余 → approval 问人。
    """
    if tool_name == "AskUserQuestion":
        questions = input_data.get("questions", [])
        resp = await ask_host_blocking("question", {"questions": questions})
        return PermissionResultAllow(
            updated_input={"questions": questions, "answers": resp.get("answers", {})}
        )

    detail = str(input_data)[:300]
    resp = await ask_host_blocking("approval", {
        "prompt": f"工具需要授权: {tool_name}",
        "detail": detail,
    })
    if resp.get("approved"):
        return PermissionResultAllow(updated_input=input_data)
    return PermissionResultDeny(message=resp.get("message", "宿主拒绝执行。"))


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
        hooks={
            "PreToolUse": [HookMatcher(matcher="*", hooks=[gate_pre_tool_use])],
        },
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
                            # 完整打印：报告类长文本不能被截断（观测盲点教训，2026-09-07）
                            print(f"\n🤖 claude:\n{block.text}")
            elif isinstance(msg, SystemMessage):
                sub = msg.subtype
                if sub == "init":
                    print(f"[会话] session_id={msg.data.get('session_id', '?')[:16]}...")
                elif sub in ("control_request", "control_response"):
                    print(f"[控制] {sub}: {str(msg.data)[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
