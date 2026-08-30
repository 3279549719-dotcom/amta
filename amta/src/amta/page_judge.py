"""page_judge — Stage 1 半自主循环：每页结束后 AI 质量判断 + 自动决策。

这是 translate_tools.run_tool_loop 模式的放大版：
- AI 看当前页的 canon（OCR）+ translation（译文）+ semantic（四维评分）
- 通过 function calling 决定：pass / repair / ticket
- 决策结果落盘，供 00_run_all 自动执行

设计原则（ADR-018 零依赖自造薄层）：
- 不引 LangGraph 等框架，复用 chat_client + translate_tools 的工具循环模式
- 只在每页结束时调一次 LLM，成本可控
- 默认关闭（--with-judge），不破坏现有流水线
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from amta.chat_client import chat
from amta.paths import read_json, write_json

# 决策工具 schema（OpenAI 兼容 function calling 格式）
JUDGE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "pass_page",
            "description": "本页翻译质量合格，通过验收，继续下一页。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "通过的理由（一句话）"},
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repair_region",
            "description": "某个 region 的译文有问题，需要自动修复。调用后系统会自动跑 repair_failed。",
            "parameters": {
                "type": "object",
                "properties": {
                    "region_id": {"type": "string", "description": "要修复的 region_id，如 page_10_u03"},
                    "reason": {"type": "string", "description": "问题描述（错译/漏译/生硬/术语不一致等）"},
                },
                "required": ["region_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_ticket",
            "description": "问题复杂或需要人工判断，开 needs_review 工单，继续下一页不等人工。",
            "parameters": {
                "type": "object",
                "properties": {
                    "region_id": {"type": "string", "description": "有问题的 region_id"},
                    "reason": {"type": "string", "description": "需要人工判断的原因"},
                    "kind": {
                        "type": "string",
                        "enum": ["term_conflict", "false_positive", "hard_case", "unknown"],
                        "description": "工单分类",
                    },
                },
                "required": ["region_id", "reason"],
            },
        },
    },
]

SYSTEM_PROMPT = """你是漫画翻译质量验收官。你的任务是检查当前页的翻译质量，决定：
1. pass_page —— 质量合格，通过
2. repair_region —— 某个框有问题，自动修复
3. open_ticket —— 问题复杂，需要人工判断

判断标准：
- 语义评分（accuracy/fluency/consistency/readability）低于 3 分的框优先考虑 repair
- 术语不一致、角色名译错、漏译、明显错译 → repair
- 语境歧义、文化梗、需要看前后页才能判断的 → open_ticket
- 全部合格或只有小瑕疵不影响理解 → pass_page

你可以多次调用工具（比如修复两个框，再 pass）。所有工具调用完成后，输出一句总结。"""


def _build_user_message(canon: list[dict], translation: dict[str, str],
                        semantic: dict[str, Any]) -> str:
    """组装给 AI 的当前页信息：OCR 文本 + 译文 + 语义评分。"""
    lines = ["## 当前页 OCR 文本与译文"]
    for r in canon:
        rid = r["region_id"]
        src = r.get("text", "")
        trans = translation.get(rid, "(缺失)")
        lines.append(f"- {rid}: 「{src}」→「{trans}」")

    if semantic.get("failed"):
        lines.append("\n## 语义检查未通过的框")
        for item in semantic.get("failed", []):
            rid = item.get("region_id", "?")
            scores = item.get("scores", {})
            reason = item.get("reason", "")
            lines.append(f"- {rid}: scores={scores} reason={reason}")

    if semantic.get("results"):
        lines.append("\n## 全部框语义评分")
        for item in semantic.get("results", []):
            rid = item.get("region_id", "?")
            scores = item.get("scores", {})
            lines.append(f"- {rid}: {scores}")

    return "\n".join(lines)


def judge_page(canon_path: Path | str, trans_path: Path | str,
               sem_path: Path | str, *,
               base_url: str, model: str, api_key: str,
               max_rounds: int = 4) -> dict[str, Any]:
    """对单页做 AI 质量判断，返回决策列表。

    Args:
        canon_path: canon_text.json（OCR 结果）
        trans_path: translation.json（译文）
        sem_path: semantic_check.json（语义评分）
        base_url/model/api_key: DeepSeek API 配置
        max_rounds: 工具循环最大轮次（防死循环）

    Returns:
        {"decisions": [{"tool": "pass_page|repair_region|open_ticket", "args": {...}, ...}], "summary": str}
    """
    canon = read_json(canon_path)
    translation = read_json(trans_path).get("translations", {})
    semantic = read_json(sem_path) if Path(sem_path).exists() else {}

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(canon, translation, semantic)},
    ]

    decisions: list[dict[str, Any]] = []
    summary = ""

    for _ in range(max_rounds):
        resp = chat(base_url, model, messages, tools=JUDGE_TOOLS, api_key=api_key)
        content = resp.get("content") or ""
        calls = resp.get("tool_calls") or []

        if not calls:
            summary = content
            break

        messages.append({"role": "assistant", "content": content or None,
                         "tool_calls": calls})

        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            decisions.append({"tool": name, "args": args})
            # 工具执行结果回传（Stage 1 只记录决策，实际执行由 00_run_all 做）
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": f"已记录决策：{name}({args})",
            })

    return {"decisions": decisions, "summary": summary}


def save_decision(out_path: Path | str, decision: dict[str, Any]) -> Path:
    """把判断结果落盘。"""
    return write_json(out_path, decision)
