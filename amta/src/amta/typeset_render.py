"""渲染器(Stage 5): 横排居中 / 竖排多列 / 白色描边。就地绘制到 PIL Image。

ADR-031 决策C：render_item 不再接收 direction，由 fit_font_size 双方向选优返回。
竖排支持多列（从右到左排列，每列从上到下），与横排多行对称。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from amta.typeset_engine import fit_font_size, CHAR_WIDTH_RATIO, LINE_HEIGHT_RATIO


def render_item(img: Image.Image, text: str, font_path: str, bbox: list,
                stroke: int, color=(0, 0, 0)) -> dict:
    """渲染一条译文到 img(就地修改)。

    返回 {layout_direction, font_size, lines, anchor_pos}。
    横排: 多行居中于 bbox 中心; 竖排: 多列从右到左排列，每列从上到下。
    方向由 fit_font_size 双方向计算自动选择（字号更大者）。
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    font_size, direction, lines = fit_font_size(text, Path(font_path), bbox)
    font = ImageFont.truetype(font_path, font_size)
    draw = ImageDraw.Draw(img)
    lh = int(font_size * LINE_HEIGHT_RATIO)

    if direction == "vertical":
        # 竖排多列：从右到左排列，每列从上到下
        n_cols = len(lines)
        col_width = font_size * CHAR_WIDTH_RATIO
        total_w = n_cols * col_width
        # 最右列的 x 坐标（列中心）
        x_start = cx + total_w / 2 - col_width / 2
        for col_idx, col_text in enumerate(lines):
            x = x_start - col_idx * col_width
            col_h = len(col_text) * lh
            y = cy - col_h // 2
            for ch in col_text:
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
