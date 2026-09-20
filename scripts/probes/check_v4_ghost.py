"""检查 V4 文字墨迹在白泡上是否留残影：p16 几个白泡 clean 全分辨率对比。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(r"E:\manga translator agent")
sys.path.insert(0, str(ROOT / "src"))
from PIL import Image

CMP = ROOT / "output" / "inpaint-compare"
OUT = ROOT / "output" / "inpaint-pixel-check"
OUT.mkdir(exist_ok=True)

CASES = [
    (16, "r04_左上白泡", (200, 80, 430, 440)),
    (16, "r00_右中白泡", (1170, 1150, 1460, 1540)),
    (21, "r03_横排说明框", (780, 1830, 1350, 2000)),
]

for page, name, (x1, y1, x2, y2) in CASES:
    paths = {
        "V1现状": CMP / "V1_current" / f"page_{page}_clean.png",
        "V4墨迹HR": CMP / "V4_textink_hr" / f"page_{page}_clean.png",
    }
    rows = []
    for label, p in paths.items():
        if p.exists():
            rows.append((label, Image.open(p).convert("RGB").crop((x1, y1, x2, y2))))
    gap = 16
    w = sum(r.width for _, r in rows) + gap * (len(rows) - 1)
    h = max(r.height for _, r in rows)
    canvas = Image.new("RGB", (w, h), (255, 0, 0))
    cx = 0
    for _, r in rows:
        canvas.paste(r, (cx, 0)); cx += r.width + gap
    if canvas.width > 1100:
        sc = 1100 / canvas.width
        canvas = canvas.resize((1100, int(canvas.height * sc)), Image.LANCZOS)
    outp = OUT / f"p{page}_{name}_V1_vs_V4.png"
    canvas.save(outp)
    print(outp)
