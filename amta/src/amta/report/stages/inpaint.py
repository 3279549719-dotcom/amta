"""inpaint 阶段适配器 — inpaint修复结果 → StageOutput（深接口）。

单元格渲染：该框区域在 inpaint 后 clean 图上的裁剪缩略图。
page_artifact：整页 clean 图（用于报告顶部2图并列）。
"""
from __future__ import annotations

import base64
import io
from typing import Any

from PIL import Image

from ..model import StageOutput


def _crop_to_b64(img: Image.Image, bbox: list[float], max_w: int = 180) -> str:
    """按 bbox 裁剪并缩放，返回 base64 JPEG。"""
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(img.width, x2), min(img.height, y2)
    if x2 <= x1 or y2 <= y1:
        return ""
    crop = img.crop((x1, y1, x2, y2))
    if crop.width > max_w:
        ratio = max_w / crop.width
        crop = crop.resize((max_w, int(crop.height * ratio)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


def render_cell(data: Any) -> str:
    """表格单元格渲染：inpaint后裁剪缩略图。"""
    if not data:
        return '<span style="color:#999;font-size:11px">(无)</span>'
    img_b64 = data.get("clean_crop_b64", "")
    if not img_b64:
        return '<span style="color:#999;font-size:11px">(无)</span>'
    return (f'<img src="data:image/jpeg;base64,{img_b64}" '
            f'style="max-width:180px;border-radius:4px;border:1px solid #e5e7eb">')


def from_inpaint(clean_img: Image.Image,
                  bboxes: dict[str, list[float]]) -> StageOutput:
    """inpaint后的clean图 + 各框bbox → StageOutput。

    Args:
        clean_img: inpaint后的整页clean图 (RGB)
        bboxes: {region_id: [x1,y1,x2,y2]}，只传 text_free 框
    """
    cells: dict[str, Any] = {}
    for rid, bbox in bboxes.items():
        cells[rid] = {
            "bbox": bbox,
            "clean_crop_b64": _crop_to_b64(clean_img, bbox),
        }

    return StageOutput(
        key="inpaint",
        label="inpaint修复后",
        cells=cells,
        render_cell=render_cell,
        page_artifact={"clean_image": clean_img},
    )
