"""detect 阶段适配器 — detection.json → StageOutput。"""
from __future__ import annotations

from typing import Any

from ..model import StageOutput


def render_cell(data: Any) -> str:
    if not data:
        return '<span style="color:#999">(无)</span>'
    conf = data.get("confidence", 0)
    bbox = data.get("bbox", [])
    bbox_str = f"[{int(bbox[0])},{int(bbox[1])}]" if bbox else ""
    color = "#16a34a" if conf >= 0.7 else "#d97706"
    return f'<span style="color:{color};font-weight:600">{conf:.3f}</span> {btype} <span style="font-family:monospace;font-size:10px">{bbox_str}</span>'


def render_overlay(draw, blocks: dict[str, Any], scale: float, offset: int = 0) -> None:
    """在原图上画检测框（绿框 + conf 标签）。"""
    from PIL import ImageFont

    def _font(size: int):
        for name in ["msyh.ttc", "simhei.ttf", "arial.ttf"]:
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    font = _font(14)
    for rid, data in blocks.items():
        bbox = data.get("bbox", [0, 0, 0, 0])
        x1, y1, x2, y2 = [int(v * scale) for v in bbox]
        y1 += offset
        y2 += offset
        conf = data.get("confidence", 0)
        color = (34, 197, 94) if conf >= 0.7 else (217, 119, 6)
        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
        label = f"{rid} {conf:.2f}"
        tw = draw.textlength(label, font=font)
        draw.rectangle([x1, max(0, y1 - 20), x1 + tw + 6, y1], fill=(0, 0, 0))
        draw.text((x1 + 3, max(0, y1 - 18)), label, fill=(255, 255, 255), font=font)


def from_detection(det: dict) -> StageOutput:
    """detection.json → StageOutput。"""
    cells: dict[str, Any] = {}
    for b in det.get("blocks", []):
        rid = b.get("region_id", "")
        if rid:
            cells[rid] = {
                "bbox": b.get("bbox", []),
                "confidence": b.get("confidence", 0),
            }
    return StageOutput(
        key="detect",
        label=f"检测 (conf={det.get('conf_threshold', '?')})",
        cells=cells,
        render_cell=render_cell,
        render_overlay=render_overlay,
    )
