"""ocr 阶段适配器 — canon.json → StageOutput。"""
from __future__ import annotations

from typing import Any

from ..model import StageOutput


def render_cell(data: Any) -> str:
    if not data:
        return '<span style="color:#dc2626">(缺失)</span>'
    text = data.get("text", "")
    if not text:
        return '<span style="color:#999">(空)</span>'
    import html
    return f'<span style="font-family:monospace;font-size:11px">{html.escape(text)}</span>'


def from_canon(canon: dict) -> StageOutput:
    """canon.json → StageOutput（OCR 文本）。"""
    cells: dict[str, Any] = {}
    for item in canon.get("items", []):
        rid = item.get("region_id", "")
        if rid:
            cells[rid] = {
                "text": item.get("baberu_text") or item.get("text") or "",
                "bbox": item.get("bbox", []),
                "category": item.get("category", ""),
            }
    return StageOutput(
        key="ocr",
        label="OCR (baberu)",
        cells=cells,
        render_cell=render_cell,
    )
