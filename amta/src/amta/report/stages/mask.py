"""mask 阶段适配器 — 精修mask结果 → StageOutput（深接口）。

方案A：框内传统方法（Otsu + 颜色直方图 + 连通域）精修像素级mask。
单元格渲染：该框区域的 mask 叠加缩略图（半透明红覆盖在原图上）。
"""
from __future__ import annotations

import base64
import io
from typing import Any

import numpy as np
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


def _build_mask_overlay(raw_img: Image.Image, mask_np: np.ndarray) -> Image.Image:
    """把精修mask以半透明红色叠加到原图上。"""
    overlay = raw_img.convert("RGBA")
    mask_pil = Image.fromarray(mask_np)
    red_layer = Image.new("RGBA", mask_pil.size, (239, 68, 68, 90))
    overlay.paste(red_layer, mask=mask_pil)
    return overlay.convert("RGB")


def render_cell(data: Any) -> str:
    """表格单元格渲染：mask叠加缩略图。"""
    if not data:
        return '<span style="color:#999;font-size:11px">(无)</span>'
    img_b64 = data.get("mask_crop_b64", "")
    if not img_b64:
        return '<span style="color:#999;font-size:11px">(无mask)</span>'
    return (f'<img src="data:image/jpeg;base64,{img_b64}" '
            f'style="max-width:180px;border-radius:4px;border:1px solid #e5e7eb">')


def from_mask(raw_img: Image.Image, mask_np: np.ndarray,
               bboxes: dict[str, list[float]]) -> StageOutput:
    """原图 + 全页精修mask + 各框bbox → StageOutput。

    Args:
        raw_img: 原图 (RGB)
        mask_np: 全页精修mask (H,W), 255=文字像素, 0=背景
        bboxes: {region_id: [x1,y1,x2,y2]}，传所有 inpaint 框
    """
    mask_overlay = _build_mask_overlay(raw_img, mask_np)

    cells: dict[str, Any] = {}
    for rid, bbox in bboxes.items():
        cells[rid] = {
            "bbox": bbox,
            "mask_crop_b64": _crop_to_b64(mask_overlay, bbox),
        }

    return StageOutput(
        key="mask",
        label="像素精修mask",
        cells=cells,
        render_cell=render_cell,
    )
