"""渲染器(Stage 5): 横排居中 / 竖排单列 / 白色描边。就地绘制到 PIL Image。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from amta.typeset_engine import fit_font_size


def render_item(img: Image.Image, text: str, font_path: str, bbox: list,
                direction: str, stroke: int, color=(0, 0, 0)) -> dict:
    """渲染一条译文到 img(就地修改)。

    返回 {layout_direction, font_size, lines, anchor_pos}。
    横排: 多行居中于 bbox 中心; 竖排: 单列自上而下, 列 x 居中(Spec §3.3)。
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    font_size, _ = fit_font_size(text, Path(font_path), bbox, direction)
    if direction == "vertical":
        lines = [text]  # MVP 单列竖排: 整串一列(lines 语义=排版列/行)
    else:
        lines = _
    font = ImageFont.truetype(font_path, font_size)
    draw = ImageDraw.Draw(img)
    lh = int(font_size * 1.2)

    if direction == "vertical":
        total_h = len(text) * lh
        y = cy - total_h // 2
        x = cx - font_size // 2
        for ch in text:
            draw.text((x, y), ch, font=font, fill=color,
                      stroke_width=int(stroke), stroke_fill="white")
            y += lh
    else:
        total_h = len(lines) * lh
        y = cy - total_h // 2
        for line in lines:
            w = font.getlength(line)
            draw.text((cx - w / 2, y), line, font=font, fill=color,
                      stroke_width=int(stroke), stroke_fill="white")
            y += lh

    return {"layout_direction": direction, "font_size": font_size,
            "lines": lines, "anchor_pos": [cx, cy]}
