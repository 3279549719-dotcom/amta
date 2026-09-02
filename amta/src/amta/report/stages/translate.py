"""translate 阶段适配器 — translation.json → StageOutput。"""
from __future__ import annotations

from typing import Any

from ..model import StageOutput


def render_cell(data: Any) -> str:
    if not data:
        return '<span style="color:#dc2626">(缺失)</span>'
    text = data.get("translation", "")
    if not text:
        return '<span style="color:#dc2626">(空译文)</span>'
    import html
    return html.escape(text)


def from_translation(trans: dict) -> StageOutput:
    """translation.json → StageOutput。"""
    translations = trans.get("translations", {})
    cells: dict[str, Any] = {}
    for rid, text in translations.items():
        cells[rid] = {"translation": text}

    # 页级统计作为 page_artifact
    residue = trans.get("residue", [])
    glossary = trans.get("glossary_violations", [])
    return StageOutput(
        key="translate",
        label="译文",
        cells=cells,
        render_cell=render_cell,
        page_artifact={"residue": residue, "glossary_violations": glossary},
    )
