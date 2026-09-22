"""Local renderer: greedy line breaking + VLM-observed style. No plan, no retries."""
from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from amta.typeset.typeset_render import _render_vertical
from amta.typeset.vertical_punct import verticalize_text

FONTS = {"sans": "msyh.ttc", "serif": "simsun.ttc", "handwritten": "simkai.ttf", "bold": "msyhbd.ttc"}

_TOKEN_RE = re.compile(r"[A-Za-z0-9_@./=+%-]+|.")
_NO_LINE_START = set("，。！？、：；）》】〉」』…—,.!?;:")
_NO_LINE_END = set("（【《〈「『(")


def _rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def ink_width(font: ImageFont.FreeTypeFont, text: str) -> float:
    bounds = font.getbbox(text)
    return bounds[2] - bounds[0]


def wrap_horizontal(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    """Greedy line break. Latin identifiers are indivisible; kinsoku protects line edges."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for token in _TOKEN_RE.findall(paragraph):
            if line and ink_width(font, line + token) > max_width:
                # Kinsoku: don't start a line with closing punctuation — pull the last char down.
                if token in _NO_LINE_START and len(line) > 1:
                    lines.append(line[:-1].rstrip())
                    line = line[-1] + token
                    continue
                # Don't end a line with opening punctuation — push it to the next line.
                if line and line[-1] in _NO_LINE_END:
                    if len(line) > 1:
                        lines.append(line[:-1].rstrip())
                        line = line[-1] + token
                    else:
                        line += token
                    continue
                lines.append(line.rstrip())
                line = token.lstrip()
            else:
                line += token
        lines.append(line.rstrip())
    return lines


def _vertical_columns(text: str, chars_per_col: int) -> list[str]:
    cols: list[str] = []
    for paragraph in text.split("\n"):
        for i in range(0, max(1, len(paragraph)), chars_per_col):
            cols.append(paragraph[i:i + chars_per_col])
        if not paragraph:
            cols.append("")
    return [c for c in cols if c] or [""]


def layout_text(text: str, block: dict, image_size: tuple[int, int]) -> dict:
    """Find the largest font size at or below the VLM-requested ratio that fits the region."""
    x1, y1, x2, y2 = map(float, block["bbox"])
    width, height = x2 - x1, y2 - y1
    font_path = str(Path("C:/Windows/Fonts") / FONTS[block["font"]])
    direction = block["direction"]
    requested = max(1, round(max(image_size) * float(block.get("font_size_ratio", 0.04))))
    line_spacing = float(block.get("line_spacing", 1.3))
    for size in range(requested, 0, -1):
        font = ImageFont.truetype(font_path, size)
        stroke = round(size * float(block.get("stroke_ratio", 0)))
        if direction == "horizontal":
            lines = wrap_horizontal(text, font, width - 2 * stroke)
            if not lines:
                continue
            step = math.ceil(size * line_spacing)
            heights = [font.getbbox(line or "字")[3] - font.getbbox(line or "字")[1] for line in lines]
            used_h = (len(lines) - 1) * step + max(heights) + 2 * stroke
            used_w = max(ink_width(font, line) for line in lines) + 2 * stroke
        else:
            cpc = max(1, int((height - 2 * stroke) / (sum(font.getmetrics()) * line_spacing)))
            lines = _vertical_columns(text, cpc)
            step = math.ceil(sum(font.getmetrics()) * line_spacing)
            col_width = font.getlength("字") * line_spacing
            used_w = len(lines) * col_width + 2 * stroke
            used_h = max(map(len, lines)) * step + 2 * stroke
        if used_w <= width and used_h <= height:
            align = block.get("align", "center")
            if direction == "horizontal":
                x = x1 if align == "left" else x2 - used_w if align == "right" else x1 + (width - used_w) / 2
                y = y1
            else:
                x = x1 + (width - used_w) / 2
                y = y1 + (height - used_h) / 2
            return {"layout_direction": direction, "font_size": size, "font_path": font_path,
                    "lines": lines, "line_step": step, "stroke_width": stroke,
                    "align": align, "bbox": block["bbox"],
                    "ink_bbox": [x, y, x + used_w, y + used_h],
                    "font": block["font"], "color": block.get("color", "#000000"),
                    "stroke_color": block.get("stroke_color"), "stroke_ratio": block.get("stroke_ratio", 0),
                    "font_size_ratio": block.get("font_size_ratio", 0.04)}
    raise ValueError("text cannot fit region")


def render_text(img: Image.Image, text: str, block: dict) -> dict:
    meta = layout_text(text, block, img.size)
    font = ImageFont.truetype(meta["font_path"], meta["font_size"])
    draw = ImageDraw.Draw(img)
    color = _rgb(meta["color"])
    stroke = meta["stroke_width"]
    stroke_fill = _rgb(meta["stroke_color"]) if meta["stroke_color"] else color
    if meta["layout_direction"] == "vertical":
        if stroke and stroke_fill != (255, 255, 255):
            raise ValueError("vertical renderer supports white stroke only")
        ix1, iy1, ix2, iy2 = meta["ink_bbox"]
        _render_vertical(img, draw, font, [verticalize_text(s) for s in meta["lines"]],
                         (ix1 + ix2) / 2, (iy1 + iy2) / 2, meta["font_size"], meta["line_step"],
                         col_width=(ix2 - ix1 - 2 * stroke) / max(1, len(meta["lines"])),
                         stroke=stroke, color=color, main_font_path=meta["font_path"])
    else:
        y = meta["ink_bbox"][1] + stroke
        x1, _y1, x2, _y2 = block["bbox"]
        for line in meta["lines"]:
            length = ink_width(font, line) + 2 * stroke
            x = x1 if meta["align"] == "left" else x2 - length if meta["align"] == "right" else (x1 + x2 - length) / 2
            x += stroke
            bounds = font.getbbox(line or "字")
            draw.text((x - bounds[0], y - bounds[1]), line, font=font, fill=color,
                      stroke_width=stroke, stroke_fill=stroke_fill)
            y += meta["line_step"]
    return meta
