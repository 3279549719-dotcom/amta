"""
probe_sdk_decision.py — SDK 决策点闭环探针 v2（2026-09-07，官方 AskUserQuestion 标准方式）

验证三件事：
1. SDK 能启动 claude 并收到事件流 ✅
2. claude 调用 AskUserQuestion 问人 → can_use_tool 回调收到问题+选项 ✅
3. 宿主返回 answers → claude 继续 → 结构化收尾（ResultMessage）✅

用 ClaudeSDKClient（无 prompt 流，query() 保活，无需 dummy hook）。

跑法：uv run python scripts/probes/probe_sdk_decision.py
"""

import asyncio
import sys

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)
from claude_agent_sdk.types import PermissionResultAllow, ToolPermissionContext


PROMPT = (
    "这是一个 SDK 能力验证任务，请严格按顺序执行：\n"
    "1. 调用 AskUserQuestion 工具，向宿主问一个问题：'我该继续执行验证任务吗？'，"
    "选项给出两个：'继续' 和 '停止'。\n"
    "2. 宿主回答后，根据回答继续：如果宿主选择'继续'，输出 VERIFIED-OK 并结束；"
    "如果选择'停止'，输出 VERIFIED-STOP 并结束。\n"
    "3. 全程不要做任何文件操作，不要调用其他工具。"
)


async def handle_tool_request(
    tool_name: str, input_data: dict, context: ToolPermissionContext
):
    """can_use_tool 回调：AskUserQuestion 走自动回答，其余 allow。"""
    if tool_name == "AskUserQuestion":
        questions = input_data.get("questions", [])
        answers = {}
        for q in questions:
            qtext = q.get("question", "")
            opts = q.get("options", [])
            print(f"[QUESTION] {qtext}")
            for i, o in enumerate(opts):
                print(f"  [{i}] {o.get('label')}: {o.get('description', '')}")
            # 模拟用户：选第一个选项（"继续"）
            pick = opts[0].get("label", "") if opts else ""
            answers[qtext] = pick
            print(f"[HOST-ANSWER] 自动选择: {pick!r}")
        return PermissionResultAllow(
            updated_input={"questions": questions, "answers": answers}
        )
    # 其他工具直接放行
    return PermissionResultAllow(updated_input=input_data)


async def main() -> int:
    options = ClaudeAgentOptions(
        cwd=r"E:\manga translator agent\amta",
        model="deepseek-v4-flash",
        can_use_tool=handle_tool_request,
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.connect()
        await client.query(PROMPT)
        async for msg in client.receive_response():
            if isinstance(msg, ResultMessage):
                print(f"[RESULT] subtype={msg.subtype} is_error={msg.is_error} "
                      f"terminal_reason={msg.terminal_reason!r}")
                print(f"[RESULT] text={str(msg.result)[:300]!r}")
                return 0
            elif isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        print(f"[TOOL_USE] name={block.name!r} input={str(block.input)[:200]!r}")
                    elif isinstance(block, TextBlock):
                        print(f"[TEXT] {block.text[:200]!r}")
            # 其他事件（HookEvent/System）忽略，不刷屏

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
