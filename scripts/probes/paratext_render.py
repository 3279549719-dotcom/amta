"""Measured typography for visually observed blocks, independent of page identity."""
from __future__ import annotations

import math
import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from amta.typeset.typeset_render import _render_vertical
from amta.typeset.vertical_punct import verticalize_text

FONTS = {"sans": "msyh.ttc", "serif": "simsun.ttc", "handwritten": "simkai.ttf", "bold": "msyhbd.ttc"}


def ink_width(font: ImageFont.FreeTypeFont, text: str) -> float:
    bounds = font.getbbox(text)
    return bounds[2] - bounds[0]


def wrap_text(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    """Measure glyph advances; Latin identifiers are indivisible tokens."""
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for token in re.findall(r"[A-Za-z0-9_@./=+%-]+|.", paragraph):
            if line and ink_width(font, line + token) > width:
                if (token in "，。！？、：；" or unicodedata.category(token[0]) in ("Pe", "Pf")) and len(line) > 1:
                    lines.append(line[:-1].rstrip())
                    line = line[-1] + token
                    continue
                lines.append(line.rstrip())
                line = token.lstrip()
            else:
                line += token
        lines.append(line.rstrip())
    return lines


def layout_text(text: str, block: dict) -> dict:
    x1, y1, x2, y2 = block["bbox"]
    width, height = x2 - x1, y2 - y1
    font_path = str(Path("C:/Windows/Fonts") / FONTS[block["font"]])
    direction = block["direction"]
    source_lines = block.get("source_lines") or [block.get("text", text)]
    # Source line count and longest line constrain scale in the observed direction.
    unit = ImageFont.truetype(font_path, 100)
    n_lines = max(1, len(source_lines))
    if direction == "horizontal":
        longest = max(unit.getlength(s) / 100 for s in source_lines) or 1
        source_size = min(width / longest, height / (1 + (n_lines - 1) * 1.35))
    else:
        source_size = min(height / max(1, max(map(len, source_lines))), width / (n_lines * 1.3))
    for sz in range(max(1, int(source_size)), 0, -1):
        font = ImageFont.truetype(font_path, sz)
        if direction == "horizontal":
            lines = wrap_text(text, font, width)
            ink_heights = [font.getbbox(s or "字")[3] - font.getbbox(s or "字")[1] for s in lines]
            step = math.ceil(sz * 1.35)
            used_h = (len(lines) - 1) * step + max(ink_heights)
            used_w = max(ink_width(font, s) for s in lines)
        else:
            cpc = max(1, int(height / (sum(font.getmetrics()))))
            lines = [part[i:i+cpc] for part in text.split("\n") for i in range(0, max(1, len(part)), cpc)]
            used_w = len(lines) * font.getlength("字")
            used_h = max(map(len, lines)) * sum(font.getmetrics())
            step = sum(font.getmetrics())
        if used_w <= width and used_h <= height:
            y = y1 if block["align"] == "left" and direction == "horizontal" else y1 + (height - used_h) / 2
            x = x1 if block["align"] == "left" else x2-used_w if block["align"] == "right" else (x1+x2-used_w)/2
            return {"layout_direction": direction, "font_size": sz, "font_path": font_path,
                    "lines": lines, "line_step": step, "align": block["align"],
                    "bbox": block["bbox"], "ink_bbox": [x, y, x + used_w, y + used_h],
                    "source_font_size": source_size}
    raise ValueError("text cannot fit region")


def render_text(img: Image.Image, text: str, block: dict) -> dict:
    meta = layout_text(text, block)
    font = ImageFont.truetype(meta["font_path"], meta["font_size"])
    x1, y1, x2, y2 = block["bbox"]
    draw = ImageDraw.Draw(img)
    if meta["layout_direction"] == "vertical":
        _render_vertical(img, draw, font, [verticalize_text(s) for s in meta["lines"]],
                         (x1+x2)/2, (y1+y2)/2, meta["font_size"], sum(font.getmetrics()),
                         col_width=font.getlength("字"), stroke=0, color=(0, 0, 0),
                         main_font_path=meta["font_path"])
    else:
        y = meta["ink_bbox"][1]
        for line in meta["lines"]:
            length = ink_width(font, line)
            x = x1 if block["align"] == "left" else x2-length if block["align"] == "right" else (x1+x2-length)/2
            draw.text((x-font.getbbox(line)[0], y - font.getbbox(line or "字")[1]), line, font=font, fill="black")
            y += meta["line_step"]
    return meta
