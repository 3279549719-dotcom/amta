"""渲染器(Stage 5): 横排居中 / 竖排多列 / 白色描边。就地绘制到 PIL Image。

ADR-033 决策C：render_item 不再接收 direction，由 fit_font_size 双方向选优返回。
竖排支持多列（从右到左排列，每列从上到下），与横排多行对称。
方向推断：从 bbox 长宽比推断原文方向，作为 preferred_direction 传入 fit_font_size。

2026-09-11 基准字号改造：render_item 新增 base_size 参数，传给 fit_font_size。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat

from amta.typeset.typeset_engine import fit_font_size, infer_direction_from_bbox


def _decide_color_and_stroke(img: Image.Image, bbox: list,
                             suggested_color, suggested_stroke,
                             font_size: int) -> tuple[tuple, int]:
    """采样 bbox 区域背景，自适应决定字色和描边宽度。

    第一性原理：文字可读需要对比度。
    - 亮底平背景（亮度高、方差小）→ 黑字无描边
    - 暗底（亮度低）→ 白字反色
    - 碎底（网点/斜线，方差大）→ 黑字 + 白描边
    - 中间灰 → 黑字 + 细白描边
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    region = img.crop((x1, y1, x2, y2)).convert("L")
    if region.width == 0 or region.height == 0:
        return suggested_color, suggested_stroke
    # 灰度统计用 ImageStat（C 实现）：替代手工像素循环，修复 pyright ImagingCore 协议违规
    stat = ImageStat.Stat(region)
    brightness = stat.mean[0]
    # 方差：衡量背景纹理复杂度
    variance = stat.stddev[0] ** 2

    if brightness > 140 and variance < 800:
        # 亮底平背景：黑字不描边
        return (0, 0, 0), 0
    if brightness < 80:
        # 暗底：白字反色，不需要描边
        return (255, 255, 255), 0
    if variance > 1500:
        # 碎底（网点/斜线）：黑字 + 白描边
        return (0, 0, 0), max(2, int(font_size * 0.08))
    # 中间灰/低对比度：黑字 + 细白描边
    return (0, 0, 0), max(1, int(font_size * 0.05))


def render_item(img: Image.Image, text: str, font_path: str, bbox: list,
                stroke: int, color=(0, 0, 0),
                preferred_direction: str | None = None,
                base_size: int | None = None) -> dict:
    """渲染一条译文到 img(就地修改)。

    preferred_direction: 首选排版方向（"horizontal"|"vertical"|None）。
        若为 None，自动从 bbox 长宽比推断。
        传入显式值时覆盖自动推断。

    base_size: 基准字号（px）。传入时大框不撑满、小框才缩小到相对下限。
        None 时用旧行为（框内最大化字号）。

    返回 {layout_direction, font_size, lines, anchor_pos, preferred_direction}。
    横排: 多行居中于 bbox 中心; 竖排: 多列从右到左排列，每列从上到下。
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    # 方向推断：尊重调用方显式指定；None 时从 bbox 长宽比几何推断（9-16 债务修复）
    if preferred_direction is None:
        preferred_direction = infer_direction_from_bbox(bbox)
    font_size, direction, lines = fit_font_size(
        text, Path(font_path), bbox, preferred_direction=preferred_direction,
        base_size=base_size
    )
    font = ImageFont.truetype(font_path, font_size)
    draw = ImageDraw.Draw(img)
    # 精确行高和字宽（与 _fits 的测量方式一致，避免测量/渲染不一致导致溢出）
    ascent, descent = font.getmetrics()
    lh = ascent + descent
    col_w = font.getlength("字")

    # 背景自适应：覆盖传入的 color/stroke
    color, stroke = _decide_color_and_stroke(img, bbox, color, stroke, font_size)

    if direction == "vertical":
        _render_vertical(img, draw, font, lines, cx, cy, font_size, lh,
                         col_width=col_w,
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
            "preferred_direction": preferred_direction,
            "rendered_color": f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}",
            "rendered_stroke": stroke}


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
        # 竖排列顶对齐：所有列顶部对齐到同一水平线（整组列垂直居中），
        # 不再每列各自居中导致短列漂浮。
        max_col_h = max(len(c) for c in lines) * lh
        y = cy - max_col_h // 2
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
