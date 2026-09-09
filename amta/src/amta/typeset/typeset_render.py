"""渲染器(Stage 5): 横排居中 / 竖排多列 / 白色描边。就地绘制到 PIL Image。

ADR-031 决策C：render_item 不再接收 direction，由 fit_font_size 双方向选优返回。
竖排支持多列（从右到左排列，每列从上到下），与横排多行对称。
方向推断：从 bbox 长宽比推断原文方向，作为 preferred_direction 传入 fit_font_size。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from amta.typeset.typeset_engine import (CHAR_WIDTH_RATIO, LINE_HEIGHT_RATIO,
                                 fit_font_size, infer_direction_from_bbox)


def render_item(img: Image.Image, text: str, font_path: str, bbox: list,
                stroke: int, color=(0, 0, 0),
                preferred_direction: str | None = None) -> dict:
    """渲染一条译文到 img(就地修改)。

    preferred_direction: 首选排版方向（"horizontal"|"vertical"|None）。
        若为 None，自动从 bbox 长宽比推断。
        传入显式值时覆盖自动推断。

    返回 {layout_direction, font_size, lines, anchor_pos, preferred_direction}。
    横排: 多行居中于 bbox 中心; 竖排: 多列从右到左排列，每列从上到下。
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    # 未指定首选方向时，从 bbox 长宽比自动推断
    if preferred_direction is None:
        preferred_direction = infer_direction_from_bbox(bbox)
    font_size, direction, lines = fit_font_size(
        text, Path(font_path), bbox, preferred_direction=preferred_direction
    )
    font = ImageFont.truetype(font_path, font_size)
    draw = ImageDraw.Draw(img)
    lh = int(font_size * LINE_HEIGHT_RATIO)

    if direction == "vertical":
        _render_vertical(img, draw, font, lines, cx, cy, font_size, lh,
                         col_width=font_size * CHAR_WIDTH_RATIO,
                         stroke=stroke, color=color)
    else:
        total_h = len(lines) * lh
        y = cy - total_h // 2
        for line in lines:
            w = font.getlength(line)
            draw.text((cx - w / 2, y), line, font=font, fill=color,
                      stroke_width=int(stroke), stroke_fill="white")
            y += lh

    return {"layout_direction": direction, "font_size": font_size,
            "lines": lines, "anchor_pos": [cx, cy],
            "preferred_direction": preferred_direction}


def _render_vertical(img, draw, font, lines, cx, cy, font_size, lh,
                     col_width, stroke, color):
    """竖排渲染：多列从右到左，连续标点并排，横向标点旋转。"""
    n_cols = len(lines)
    total_w = n_cols * col_width
    # 最右列的 x 坐标（列左边缘）
    x_start = cx + total_w / 2 - col_width
    # 需要旋转的横向标点（在竖排中应垂直显示）
    ROTATE_CHARS = set("……—–")
    # 连续标点应左右并排（！？！？等），而非上下排列
    COMBINE_PUNCT = set("！？!?")

    for col_idx, col_text in enumerate(lines):
        x = x_start - col_idx * col_width
        col_h = len(col_text) * lh
        y = cy - col_h // 2
        i = 0
        while i < len(col_text):
            ch = col_text[i]
            if ch in COMBINE_PUNCT:
                # 连续标点组：左右并排在同一行
                j = i
                while j < len(col_text) and col_text[j] in COMBINE_PUNCT:
                    j += 1
                punct_group = col_text[i:j]
                n_punct = len(punct_group)
                punct_w = col_width / n_punct
                group_x = x + (col_width - n_punct * punct_w) / 2
                for k, pch in enumerate(punct_group):
                    draw.text((group_x + k * punct_w, y), pch, font=font,
                              fill=color, stroke_width=int(stroke),
                              stroke_fill="white")
                y += lh
                i = j
            elif ch in ROTATE_CHARS:
                # 横向标点旋转90度：字符在临时画布中居中，旋转后粘贴到列中心
                _draw_rotated_char(img, font, ch, x, y, col_width, lh,
                                   stroke, color)
                y += lh
                i += 1
            else:
                draw.text((x, y), ch, font=font, fill=color,
                          stroke_width=int(stroke), stroke_fill="white")
                y += lh
                i += 1


def _draw_rotated_char(img, font, ch, x, y, col_width, lh, stroke, color):
    """绘制旋转90度的字符，确保在列中心位置。"""
    bbox_ch = font.getbbox(ch)
    ch_w = bbox_ch[2] - bbox_ch[0]
    ch_h = bbox_ch[3] - bbox_ch[1]
    pad = max(ch_w, ch_h) + 4
    char_img = Image.new("RGBA", (pad, pad), (0, 0, 0, 0))
    char_draw = ImageDraw.Draw(char_img)
    char_draw.text(((pad - ch_w) / 2 - bbox_ch[0],
                    (pad - ch_h) / 2 - bbox_ch[1]), ch,
                   font=font, fill=color,
                   stroke_width=int(stroke), stroke_fill="white")
    rotated = char_img.rotate(90, expand=True)
    # 裁剪掉旋转后的空白区域，得到紧凑的字符图
    bbox_rot = rotated.getbbox()
    if bbox_rot:
        rotated = rotated.crop(bbox_rot)
    # 粘贴到列中心位置
    paste_x = int(x + (col_width - rotated.width) / 2)
    paste_y = int(y + (lh - rotated.height) / 2)
    img.paste(rotated, (paste_x, paste_y), rotated)
