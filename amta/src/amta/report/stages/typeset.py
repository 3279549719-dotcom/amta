"""typeset 阶段适配器 — 排版结果 → StageOutput（深接口）。

单元格渲染：译文排版预览（文字 + 方向 + 字号）。
page_artifact：最终成图（final_image）。
"""
from __future__ import annotations

from typing import Any

from PIL import Image

from ..model import StageOutput


def render_cell(data: Any) -> str:
    """表格单元格渲染：排版后的译文预览 + 元信息。"""
    if not data:
        return '<span style="color:#999;font-size:11px">(无)</span>'
    lines = data.get("lines", [])
    if isinstance(lines, list):
        text = "<br>".join(str(line) for line in lines)
    else:
        text = str(lines)
    direction = data.get("layout_direction", "")
    font_size = data.get("font_size", 0)
    return (
        f'<div style="font-size:11px">'
        f'<div style="font-weight:600;color:#1e40af;line-height:1.4">{text}</div>'
        f'<div style="color:#666;font-size:10px;margin-top:2px">{direction} · {font_size}px</div>'
        f"</div>"
    )


def from_typeset(typeset_data: dict,
                 final_img: Image.Image | None = None) -> StageOutput:
    """typeset artifact → StageOutput。

    Args:
        typeset_data: page_{idx}_typeset.json 内容，含 layout + final_image
        final_img: 最终成图 PIL Image（可选，用于 page_artifact）
    """
    layout = typeset_data.get("layout", {})
    cells: dict[str, Any] = {}
    for rid, info in layout.items():
        cells[rid] = {
            "layout_direction": info.get("layout_direction", ""),
            "font_size": info.get("font_size", 0),
            "lines": info.get("lines", []),
            "anchor_pos": info.get("anchor_pos", []),
        }

    page_artifact = {"final_image": final_img} if final_img is not None else None

    return StageOutput(
        key="typeset",
        label="排版",
        cells=cells,
        render_cell=render_cell,
        page_artifact=page_artifact,
    )

