"""排版引擎核心纯函数(Stage 5, Spec §3): 方向决策/折行/避头尾/字号二分。

蓝图 fit_text_to_bubble 算法 + §2 漏洞修复(overlay_text 强制竖排)。
"""
from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

NO_START_PUNCT = "，。！？、）》】"
MIN_SIZE = 12
MAX_SIZE = 52
SAFE_RATIO = 0.85


def decide_direction(category: str | None, bbox: list, char_count: int) -> str:
    """排版方向: overlay_text 强制竖排(漏洞修复); 其余 bbox 高宽比 ≥2.2 且字数≤6 竖排。"""
    if category == "overlay_text":
        return "vertical"
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    if w > 0 and h / w >= 2.2 and char_count <= 6:
        return "vertical"
    return "horizontal"


def wrap_text(text: str, font, max_width: float) -> list[str]:
    """贪心按字折行; 溢出字符为禁行首标点且当前行非空 → 并入当前行(避头尾)。"""
    lines: list[str] = []
    cur = ""
    for ch in text:
        if font.getlength(cur + ch) <= max_width:
            cur += ch
        elif ch in NO_START_PUNCT and cur:
            cur += ch  # 禁则标点不落行首,容忍轻微溢出
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def _fits(lines: list[str], font: ImageFont.FreeTypeFont, bbox: list,
          direction: str) -> bool:
    x1, y1, x2, y2 = bbox
    w, h = (x2 - x1) * SAFE_RATIO, (y2 - y1) * SAFE_RATIO
    if direction == "vertical":
        return font.size * 1.2 <= w and len("".join(lines)) * font.size * 1.2 <= h
    max_line = max(font.getlength(ln) for ln in lines)
    return max_line <= w and len(lines) * font.size * 1.2 <= h


def fit_font_size(text: str, font_path: Path, bbox: list, direction: str,
                  min_sz: int = MIN_SIZE, max_sz: int = MAX_SIZE
                  ) -> tuple[int, list[str]]:
    """字号二分找最大可容纳。触底仍放不下 → (min_sz, 当前行) 溢出由工位/QA 处理。"""
    if not text:
        return min_sz, []
    lo, hi = min_sz, max_sz
    best, best_lines = min_sz, []
    while lo <= hi:
        mid = (lo + hi) // 2
        font = ImageFont.truetype(str(font_path), mid)
        lines = wrap_text(text, font, (bbox[2] - bbox[0]) * SAFE_RATIO)
        if lines and _fits(lines, font, bbox, direction):
            best, best_lines = mid, lines
            lo = mid + 1
        else:
            hi = mid - 1
    if not best_lines:  # 12px 也放不下
        font = ImageFont.truetype(str(font_path), min_sz)
        best_lines = wrap_text(text, font, (bbox[2] - bbox[0]) * SAFE_RATIO)
        return min_sz, best_lines
    return best, best_lines
