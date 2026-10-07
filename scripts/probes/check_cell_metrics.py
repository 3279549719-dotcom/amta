"""竖排断行的度量口径回归探针（typeset_engine 单元格口径）。

复制自 2026-10-07 修复过程中的临时探针。可独立运行复核：
    uv run python scripts/probes/check_cell_metrics.py
输出三个真实事故区域 + 对照区域的（字号, 列数, 列内容, 溢出）判断，
以及"字符数口径 vs 渲染行口径"的对照数字。

只读：不写工作区、不跑管线。
"""
from pathlib import Path

from PIL import ImageFont

from amta.typeset.typeset_engine import (
    _cell_count,
    _column_width,
    _fits,
    _font_metrics,
    fit_font_size,
)
from amta.typeset.typeset_render import _normalize_text_for_render as norm

FONT = Path("C:/Windows/Fonts/msyh.ttc")
FONT_BOLD = Path("C:/Windows/Fonts/msyhbd.ttc")
SAFE = 0.85

# label, 译文, bbox, 字体, base_size, 期望列数
CASES = [
    ("0030 r08", "这家伙...!!", [698.0, 680.0, 731.0, 783.0], FONT_BOLD, 12, 1),
    ("0033 r04", "灵梦...!?",   [450.0, 749.0, 484.0, 842.0], FONT,      14, 1),
    ("0033 r01*", "好啦我知道啦", [163.0, 1169.0, 250.0, 1355.0], FONT,   36, -1),
    ("0038 r06*", "!!",         [1115.0, 888.0, 1159.0, 1007.0], FONT_BOLD, 52, 1),
]
# * 对照：原图本来就是多列/纯标点，列数不做强制断言（-1 = 只打印）

for label, raw, bbox, fp, base, expect in CASES:
    text = norm(raw)
    size, direction, lines = fit_font_size(
        text, fp, bbox, preferred_direction="vertical", base_size=base
    )
    font = ImageFont.truetype(str(fp), size)
    cw, lh = _font_metrics(font)
    x1, y1, x2, y2 = bbox
    avail_w, avail_h = (x2 - x1) * SAFE, (y2 - y1) * SAFE
    max_rows = max(_cell_count(c) for c in lines)
    colws = [round(_column_width(c, cw, font), 1) for c in lines]
    ok = _fits(lines, font, bbox, "vertical")
    flag = ""
    if expect >= 0 and len(lines) != expect:
        flag = f"  !! 期望 {expect} 列"
    print(
        f"{label}: {size}px {direction} cols={len(lines)}{flag}\n"
        f"    lines={lines}\n"
        f"    chars={[len(c) for c in lines]} rows={[_cell_count(c) for c in lines]} "
        f"max_rows={max_rows} row_h={max_rows * lh:.0f}/{avail_h:.0f} "
        f"col_w={colws} sum={sum(colws):.0f}/{avail_w:.0f} fits={ok}"
    )
