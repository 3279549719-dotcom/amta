"""Stage 3 翻译工位 — canon → TranslationArtifact（深模块）。

minimal 模式唯一路径：1 LLM call/page, zero tools。脚本 03_translate.py 只剩 CLI。

VLM refine 已移除（2026-09-09）：不再接受 vlm_enabled / llm_vlm 参数。
"""
from __future__ import annotations

from pathlib import Path

from amta.stage3_minimal import translate_page_minimal


def translate_page(work_id: str, canon, *, state_dir: Path | str | None = None,
                   page: str | None = None,
                   raw_image_path: Path | str | None = None,
                   llm_text=None) -> dict:
    """一页 canon → 翻译产物。minimal 模式：1 call/page, zero tools。

    历史参数（with_plan/with_vision_plan/trace_enabled/crop_dir/llm/mode/
    vlm_enabled/llm_vlm）已移除——legacy 工具循环路径与 VLM refine 已删除。
    """
    return translate_page_minimal(
        work_id, canon, raw_image_path=raw_image_path,
        state_dir=state_dir, page=page,
        llm_text=llm_text)
