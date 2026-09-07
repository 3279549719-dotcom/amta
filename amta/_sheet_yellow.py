"""把 4 页黄框裁剪拼成核对大图。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"E:\manga translator agent\amta\src")

from PIL import Image, ImageDraw

OUT = Path(r"E:\manga translator agent\amta\_tiling_audit")

files = sorted(OUT.glob("p*_yellow_*.png"))
print(f"{len(files)} 个黄框")

per_row = 3
cell_w, cell_h = 460, 380
rows = (len(files) + per_row - 1) // per_row
sheet = Image.new("RGB", (cell_w * per_row, cell_h * rows), 248)
d = ImageDraw.Draw(sheet)
for i, fp in enumerate(files):
    img = Image.open(fp).convert("RGB")
    img.thumbnail((cell_w - 30, cell_h - 46), Image.LANCZOS)
    r, c = divmod(i, per_row)
    x, y = c * cell_w + 15, r * cell_h + 15
    sheet.paste(img, (x + (cell_w - 30 - img.width) // 2, y))
    d.text((x, y + cell_h - 30), fp.stem.replace("_yellow", ""), fill=(160, 40, 40))
sheet.save(OUT / "sheet_all_yellow.png")
print("saved", sheet.size)
