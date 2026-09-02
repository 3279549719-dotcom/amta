r"""Stage 3 方案 B：VLM 整页图规划。

用 DeepSeek 的 VLM 模型（deepseek-v4-flash-vision-exp）做规划阶段，
翻译阶段仍用 deepseek-v4-flash（纯文本）。

依赖：
- 原图目录 D:\我的汉化\汉化作品\东方\单翼停留之地\{page}.jpg
- .env: CHAT_API_KEY / CHAT_BASE_URL（DeepSeek）
"""
# LEGACY: preserved for --mode legacy fallback. Stable after 3 works, delete in cleanup commit.
# Minimal path (stage3_minimal.py) is default; these files are no longer called in minimal mode.
# load_page_image_base64() is reused by minimal path; rest is legacy.
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Callable

from amta.chat_client import chat
from amta.stage3_planner import (
    PLAN_TOOLS_SCHEMA,
    PlanResult,
    build_plan_prompt,
    execute_plan_tool,
    plan_budgets,
)

# 原图目录
RAW_IMAGE_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")

# DeepSeek VLM 模型名
DEEPSEEK_VISION_MODEL = "deepseek-v4-flash-vision-exp"


def _load_deepseek_config() -> dict[str, str]:
    """从 .env 加载 DeepSeek 配置。"""
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    cfg = {"base_url": "https://api.deepseek.com", "api_key": "", "model": DEEPSEEK_VISION_MODEL}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("CHAT_BASE_URL="):
                cfg["base_url"] = line.split("=", 1)[1].strip()
            elif line.startswith("CHAT_API_KEY="):
                cfg["api_key"] = line.split("=", 1)[1].strip()
    cfg["api_key"] = os.environ.get("CHAT_API_KEY", cfg["api_key"])
    cfg["base_url"] = os.environ.get("CHAT_BASE_URL", cfg["base_url"])
    return cfg


def load_page_image_base64(page: int | str) -> str | None:
    """加载整页原图为 base64 data URL。找不到返回 None。"""
    for ext in (".jpg", ".png", ".jpeg"):
        p = RAW_IMAGE_DIR / f"{page}{ext}"
        if p.exists():
            data = base64.b64encode(p.read_bytes()).decode("ascii")
            mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
            return f"data:{mime};base64,{data}"
    return None


def build_vision_plan_messages(canon: list[dict], image_data_url: str) -> list[dict]:
    """构建带整页图的规划 messages（multimodal）。"""
    text_prompt = build_plan_prompt(canon)
    vision_instruction = (
        "\n\n【视觉辅助】你现在可以看到本页的整页原图。请结合视觉信息判断：\n"
        "1. 哪些框是排线、装饰线、图像噪声、页码（标记为 invalid）\n"
        "2. 哪些框在视觉上重叠/嵌套且内容重复（标记为 duplicate）\n"
        "3. 纯文本无法判断的框，看图后可以更准确地决策\n"
        "请仔细观察每个 bbox 对应的区域在图中的实际内容。"
    )
    return [
        {
            "role": "system",
            "content": "你是漫画翻译质量规划员，使用工具标记无效框和重复框。你可以看到整页原图。",
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text_prompt + vision_instruction},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]


def make_vlm_llm() -> Callable:
    """创建用 DeepSeek VLM 的 llm 调用函数。"""
    cfg = _load_deepseek_config()

    def vlm_llm(messages: list[dict], tools: list[dict] | None = None) -> dict:
        return chat(cfg["base_url"], cfg["model"], messages,
                    tools=tools, api_key=cfg["api_key"], timeout=180)

    return vlm_llm


def run_plan_loop_vision(
    canon: list[dict],
    llm: Callable | None = None,
    *,
    page: int | str | None = None,
    image_data_url: str | None = None,
    max_rounds: int = 4,
) -> PlanResult:
    """方案 B：带整页图的规划循环。

    如果 llm 为 None，自动创建 DeepSeek VLM 调用。
    """
    # canon 必须传入 PlanResult，否则 valid_regions 属性遍历空列表恒为 []（trace n_valid=0 bug）
    plan = PlanResult(canon=canon, invalids={}, duplicates={})
    budgets = plan_budgets(canon)  # 单工具预算（跨循环共享）

    # 加载图片
    if image_data_url is None and page is not None:
        image_data_url = load_page_image_base64(page)

    if image_data_url is None:
        # 找不到图，降级为纯文本规划
        from amta.stage3_planner import run_plan_loop
        return run_plan_loop(canon, llm, max_rounds=max_rounds)

    # 如果没传 llm，用 DeepSeek VLM
    if llm is None:
        llm = make_vlm_llm()

    messages = build_vision_plan_messages(canon, image_data_url)

    for _ in range(max_rounds):
        resp = llm(messages, tools=PLAN_TOOLS_SCHEMA)
        tool_calls = resp.get("tool_calls") or []
        if not tool_calls:
            break

        # assistant 消息只 append 一次
        messages.append({
            "role": "assistant",
            "content": resp.get("content"),
            "tool_calls": tool_calls,
        })
        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                args = {}
            result = execute_plan_tool(plan, name, args, budgets=budgets)
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": json.dumps(result, ensure_ascii=False),
            })

    return plan
