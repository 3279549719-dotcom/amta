"""Stage 3 翻译工位 — canon → TranslationArtifact（深模块）。

minimal 模式唯一路径：2 LLM calls/page, zero tools。脚本 03_translate.py 只剩 CLI。
"""
from __future__ import annotations

from pathlib import Path

from amta.stage3_minimal import translate_page_minimal


def translate_page(work_id: str, canon, *, state_dir: Path | str | None = None,
                   page: str | None = None,
                   raw_image_path: Path | str | None = None,
                   llm_text=None, llm_vlm=None, vlm_enabled: bool = True) -> dict:
    """一页 canon → 翻译产物。minimal 模式：2 calls/page, zero tools。

    历史参数（with_plan/with_vision_plan/trace_enabled/crop_dir/llm/mode）已移除——
    legacy 工具循环路径已删除，详见 cleanup commit。
    """
    return translate_page_minimal(
        work_id, canon, raw_image_path=raw_image_path,
        state_dir=state_dir, page=page,
        llm_text=llm_text, llm_vlm=llm_vlm, vlm_enabled=vlm_enabled)
