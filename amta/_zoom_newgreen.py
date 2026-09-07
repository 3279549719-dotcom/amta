"""裁剪瓦片化新增的 7 个未知绿框，人眼核对。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"E:\manga translator agent\amta\src")

from PIL import Image

RAW = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT = Path(r"E:\manga translator agent\amta\_tiling_audit\newgreen_zoom")
OUT.mkdir(exist_ok=True)

# 7 个未知新增绿框（不含 6 个已知真对白）
TARGETS = [
    (14, "p14_a", [398, 1577, 461, 1688]),
    (14, "p14_b", [1255, 736, 1337, 1055]),
    (15, "p15_a", [1757, 1982, 1969, 2337]),
    (15, "p15_b", [641, 736, 732, 976]),
    (15, "p15_c", [475, 2252, 562, 2338]),
    (17, "p17_a", [789, 736, 890, 899]),
    (17, "p17_b", [1762, 736, 1834, 889]),
]

for page, name, bb in TARGETS:
    img = Image.open(RAW / f"{page}.jpg")
    pad = 10
    x1, y1 = max(0, bb[0] - pad), max(0, bb[1] - pad)
    x2, y2 = min(img.width, bb[2] + pad), min(img.height, bb[3] + pad)
    c = img.crop((x1, y1, x2, y2))
    c = c.resize((c.width * 4, c.height * 4), Image.LANCZOS)
    p = OUT / f"{name}_zoom.png"
    c.save(p)
    print(p.name, c.size)
