"""渲染器(Stage 5): 横排居中 / 竖排多列 / 白色描边。就地绘制到 PIL Image。

ADR-033 决策C：render_item 不再接收 direction，由 fit_font_size 双方向选优返回。
竖排支持多列（从右到左排列，每列从上到下），与横排多行对称。
方向推断：从 bbox 长宽比推断原文方向，作为 preferred_direction 传入 fit_font_size。

2026-09-11 基准字号改造：render_item 新增 base_size 参数，传给 fit_font_size。
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat

from amta.typeset.typeset_engine import fit_font_size, infer_direction_from_bbox
from amta.typeset.vertical_punct import VERTICAL_COMBINE, should_rotate, verticalize_text


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
    # 渲染前字符规范化（ASCII 省略号、缺字形降级），必须在断行之前。
    text = _normalize_text_for_render(text)
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
        # 竖排：把有竖排 Unicode 形式的横排标点（括号/省略号）换成竖排形式。
        # 哪些符号要旋转，由 vertical_punct.should_rotate 按 Unicode 自动判断。
        lines = [verticalize_text(ln) for ln in lines]
        _render_vertical(img, draw, font, lines, cx, cy, font_size, lh,
                         col_width=col_w,
                         stroke=stroke, color=color,
                         main_font_path=font_path)
    else:
        total_h = len(lines) * lh
        y = cy - total_h // 2
        for line in lines:
            # 逐字符画：遇到主字体缺字形的字符（如 ♡）用 fallback 字体单独画。
            chars = list(line)
            fonts = [_font_for_char(font_path, font_size, ch) for ch in chars]
            widths = [f.getlength(ch) for f, ch in zip(fonts, chars)]
            x = cx - sum(widths) / 2
            for ch, f, cw in zip(chars, fonts, widths):
                draw.text((x, y), ch, font=f, fill=color,
                          stroke_width=int(stroke), stroke_fill="white")
                x += cw
            y += lh

    return {"layout_direction": direction, "font_size": font_size,
            "lines": lines, "anchor_pos": [cx, cy],
            "preferred_direction": preferred_direction,
            "rendered_color": f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}",
            "rendered_stroke": stroke}


# --- 渲染前字符规范化（唯一真源）-------------------------------------------
# 连续 ASCII 点（≥2）是 LLM 吐出的横排省略号，归一化为全角横排省略号。
# 必须在断行前做：否则三个独立的 "." 会被 DP 拆到不同行/列。
_ASCII_DOTS = re.compile(r"\.{2,}")


def _normalize_text_for_render(text: str) -> str:
    """渲染前的字符规范化（与排版方向无关）：连续 ASCII 点 → 全角省略号。"""
    return _ASCII_DOTS.sub("…", text)


# --- 字符级字体 fallback ---------------------------------------------------
# 主字体（微软雅黑）对某些符号是 .notdef 空框（♡/❤ 实测），但整句对白仍要保持雅黑风格。
# 做法：不改字符、不换整句字体，只把"主字体画不出来的那一个字"借一个有真字形的字体画。
# 已像素实测（渲染 vs 私用区 .notdef 对比）：msyh.ttc 缺 ♡(U+2661)/❤(U+2665)；
# NotoSansSC-VF.ttf（思源黑体，同为中文黑体，笔画粗细与雅黑协调）有真爱心。
# 以后再冒出画成方框的符号，往这里加一行 字符→字体文件 即可。
_FALLBACK_DIR = Path("C:/Windows/Fonts")
_GLYPH_FONT_FALLBACK = {
    "\u2661": "NotoSansSC-VF.ttf",
    "\u2665": "NotoSansSC-VF.ttf",
}
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _font_for_char(main_font_path: str, size: int, ch: str) -> ImageFont.FreeTypeFont:
    """渲染 ch 该用哪个字体：主字体缺字形的字符，返回有真字形的 fallback 字体。"""
    fb = _GLYPH_FONT_FALLBACK.get(ch)
    path = str(_FALLBACK_DIR / fb) if fb else main_font_path
    key = (path, size)
    hit = _font_cache.get(key)
    if hit is None:
        hit = ImageFont.truetype(path, size)
        _font_cache[key] = hit
    return hit


# --- 竖排标点规则已抽到 vertical_punct.py（接口层）-------------------------
# 哪些符号旋转、横排↔竖排形式换算，全部由 vertical_punct 按 Unicode 自动推导，
# typeset_render 只负责调用，不再维护字符名单。


def _is_horizontal_char(ch: str) -> bool:
    """判断字符是否应在竖排中横向排列（縦中横 / tate-chuu-yoko）。

    通用规则：拉丁字母、数字等非 CJK 文字在竖排中横向排列为一个整体，
    不逐字符竖排。用 Unicode 类别判断，不硬编码具体字符表。
    CJK 统一表意文字、假名、谚文保持逐字竖排。
    """
    cat = unicodedata.category(ch)
    # 拉丁字母 (Ll/Lu/Lt/Lm)、数字 (Nd) 直接横向
    if cat in ("Ll", "Lu", "Lt", "Lm", "Nd"):
        return True
    # Lo (其他字母)：排除 CJK 表意文字和假名，其余横向
    if cat == "Lo":
        cp = ord(ch)
        # CJK 统一表意、假名、谚文保持逐字竖排，其余横向
        return not (
            0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF
            or 0x3040 <= cp <= 0x30FF or 0xAC00 <= cp <= 0xD7AF
        )
    return False


def _count_vertical_lines(col_text: str) -> int:
    """计算竖排一列的实际渲染行数。

    连续横向字符（縦中横）和连续标点组合各占一行，
    不能按 len(col_text) 字符数算——否则 cosplay(9字符) 会被当成 9 行，
    导致垂直居中偏移、内容被挤出框外。
    """
    count = 0
    i = 0
    while i < len(col_text):
        ch = col_text[i]
        if ch in VERTICAL_COMBINE:
            while i < len(col_text) and col_text[i] in VERTICAL_COMBINE:
                i += 1
            count += 1
        elif _is_horizontal_char(ch):
            while i < len(col_text) and (
                _is_horizontal_char(col_text[i]) or col_text[i] == " "
            ):
                i += 1
            count += 1
        else:
            i += 1
            count += 1
    return count


def _paste_glyph_centered(img: Image.Image, font, ch: str,
                          cell_x: float, cell_y: float,
                          cell_w: float, cell_h: float,
                          stroke: int, color, rotate: bool = False) -> None:
    """原子原语：把单个字符字形贴到字格 (cell_x,cell_y,cell_w,cell_h) 的正中心。

    所有竖排字符（汉字 + 标点）都走这里，所以标点不再贴格子角。
    rotate=True 时先把字形旋转 90° 再贴（用于横躺符号立起）。
    """
    b = font.getbbox(ch)
    gw, gh = b[2] - b[0], b[3] - b[1]
    pad = max(gw, gh) + int(stroke) * 2 + 4
    cimg = Image.new("RGBA", (pad, pad), (0, 0, 0, 0))
    ImageDraw.Draw(cimg).text(
        ((pad - gw) / 2 - b[0], (pad - gh) / 2 - b[1]), ch,
        font=font, fill=color, stroke_width=int(stroke), stroke_fill="white")
    if rotate:
        cimg = cimg.rotate(90, expand=True)
    tight = cimg.getbbox()
    if tight:
        cimg = cimg.crop(tight)
    img.paste(cimg, (int(cell_x + (cell_w - cimg.width) / 2),
                     int(cell_y + (cell_h - cimg.height) / 2)), cimg)


def _render_vertical(img, draw, font, lines, cx, cy, font_size, lh,
                     col_width, stroke, color, main_font_path=None):
    """竖排渲染：多列从右到左，连续标点并排，横向标点旋转。"""
    n_cols = len(lines)
    total_w = n_cols * col_width
    # 最右列的 x 坐标（列左边缘）
    x_start = cx + total_w / 2 - col_width

    def _choose(ch: str):
        # 主字体缺字形的字符（如 ♡）用 fallback 字体；否则用主字体。
        if main_font_path is None:
            return font
        return _font_for_char(main_font_path, font_size, ch)

    for col_idx, col_text in enumerate(lines):
        x = x_start - col_idx * col_width
        # 竖排列顶对齐：所有列顶部对齐到同一水平线（整组列垂直居中），
        # 不再每列各自居中导致短列漂浮。
        # 用实际渲染行数（縦中横/标点组合各占一行），不用字符数。
        max_col_h = max(_count_vertical_lines(c) for c in lines) * lh
        y = cy - max_col_h // 2
        i = 0
        while i < len(col_text):
            ch = col_text[i]
            if ch in VERTICAL_COMBINE:
                # 连续标点组：左右并排在同一行，整体在格内均分居中
                j = i
                while j < len(col_text) and col_text[j] in VERTICAL_COMBINE:
                    j += 1
                punct_group = col_text[i:j]
                n_punct = len(punct_group)
                punct_w = col_width / n_punct
                group_x = x + (col_width - n_punct * punct_w) / 2
                for k, pch in enumerate(punct_group):
                    _paste_glyph_centered(
                        img, _choose(pch), pch,
                        group_x + k * punct_w, y, punct_w, lh,
                        stroke, color)
                y += lh
                i = j
            elif _is_horizontal_char(ch):
                # 縦中横：连续拉丁/数字字符作为一组，在当前行内横向排列。
                # 前后的半角空格跟随词组一起横向排，避免空格被单独竖排。
                j = i
                while j < len(col_text) and (
                    _is_horizontal_char(col_text[j]) or col_text[j] == " "
                ):
                    j += 1
                group = col_text[i:j]
                group_fonts = [_choose(c) for c in group]
                group_widths = [f.getlength(c) for f, c in zip(group_fonts, group)]
                total_w = sum(group_widths)
                # 组在当前字格内水平居中，超出则向两侧扩展（长单词自然占多列宽）
                gx = x + (col_width - total_w) / 2
                ascent, descent = group_fonts[0].getmetrics()
                gy = y + (lh - (ascent + descent)) / 2
                for c, f, cw in zip(group, group_fonts, group_widths):
                    draw.text((gx, gy), c, font=f, fill=color,
                              stroke_width=int(stroke), stroke_fill="white")
                    gx += cw
                y += lh
                i = j
            else:
                # 普通字符 + 需立起的横躺符号，统一走"字格居中"原语
                _paste_glyph_centered(
                    img, _choose(ch), ch, x, y, col_width, lh,
                    stroke, color, rotate=should_rotate(ch))
                y += lh
                i += 1
