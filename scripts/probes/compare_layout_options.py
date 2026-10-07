"""探针：把**当前引擎的实际选优结果**和「旧行为（字号最大优先）」在同一 bbox 内并排画出来。

只读原图 + 冻结译文，输出对比图到 artifacts/typeset-fix-20261007/。
不改生产代码，不写 workspace。

用法：
  uv run python scripts/probes/compare_layout_options.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from amta.typeset.typeset_engine import (  # noqa: E402
    _cell_rows,
    _enum_vertical_feasible,
    _vertical_pick,
    fit_font_size,
    wrap_cells_to_columns,
)
from amta.typeset.typeset_render import _render_vertical, verticalize_text  # noqa: E402

OUT = REPO / "artifacts" / "typeset-fix-20261007"
SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\タガタメ")
FONT = r"C:\Windows\Fonts\msyhbd.ttc"

# (标签, 原图, bbox, 冻结译文, base_size)
CASES = [
    ("0030-r08", "0030.png", [698, 680, 731, 783], "这家伙…!!", 14),
    ("0033-r04", "0033.png", [450, 749, 484, 842], "灵梦…!?", 14),
    ("0038-r09", "0038.png", [455, 971, 479, 1052], "好难喝…!", 12),
]


def draw_layout(bbox: list, text: str, size: int, cols: int) -> Image.Image:
    """按给定列数/字号在 bbox 内画一遍，返回 4x 放大的裁剪图。"""
    x1, y1, x2, y2 = bbox
    pad = 12
    canvas = Image.new("RGB", (pad * 2 + (x2 - x1), pad * 2 + (y2 - y1)), (255, 255, 255))
    lines = wrap_cells_to_columns(_cell_rows(text), cols) if cols >= 2 else [text]
    lines = [ln for ln in lines if ln]
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(FONT, size)
    ascent, descent = font.getmetrics()
    lh = ascent + descent
    col_w = font.getlength("字")
    vlines = [verticalize_text(ln) for ln in lines]
    _render_vertical(canvas, draw, font, vlines,
                     pad + (x2 - x1) // 2, pad + (y2 - y1) // 2,
                     size, lh, col_width=col_w, stroke=0, color=(0, 0, 0),
                     main_font_path=FONT, hide_mask=None)
    scaled = canvas.resize((canvas.width * 5, canvas.height * 5), Image.NEAREST)
    ImageDraw.Draw(scaled).text((4, 4), f"{size}px x{len(lines)}col",
                                fill=(200, 0, 0))
    return scaled


def main() -> int:
    for label, src_name, bbox, text, base in CASES:
        # 当前引擎（列数少优先，受相对下限约束）
        size, direction, lines = fit_font_size(
            text, Path(FONT), bbox, preferred_direction="vertical", base_size=base)
        # 旧行为 = 放开列数限制的最大字号那套版式
        min_sz = max(12, int(base * 0.7))
        feasible = _enum_vertical_feasible(text, Path(FONT), bbox, min_sz, base)
        if not feasible:
            feasible = _enum_vertical_feasible(text, Path(FONT), bbox, 12, 52)
        if feasible:
            ref = max(feasible)
            ref_cols = feasible[ref][0]
        else:
            # 连下限都放不下：旧行为走 fallback 折列（与引擎契约一致），新旧相同
            ref, ref_lines, _r, _one = _vertical_pick(text, Path(FONT), bbox, min_sz, base)
            ref_cols = len(ref_lines)
        note = "same as OLD (no single-column solution fits)" if (
            ref == size and ref_cols == len(lines)) else ""
        tiles = [
            draw_layout(bbox, text, size, len(lines)),
            draw_layout(bbox, text, ref, ref_cols),
        ]
        gap = 14
        W = sum(t.width for t in tiles) + gap + 20
        H = max(t.height for t in tiles) + 30
        sheet = Image.new("RGB", (W, H), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        d.text((6, 6), f"{label} bbox={bbox}  base={base}  "
                       f"NEW={size}px x{len(lines)}col   OLD(ref)={ref}px x{ref_cols}col  {note}",
               fill=(0, 0, 0))
        x = 10
        for t in tiles:
            sheet.paste(t, (x, 24))
            x += t.width + gap
        out = OUT / f"{label}_engine_vs_old.png"
        sheet.save(out, "PNG", optimize=True)
        print("wrote", out, sheet.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
