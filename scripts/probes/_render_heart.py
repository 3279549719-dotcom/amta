"""一次性探针：渲染 page33 r00 的 ♡ 文本 + ASCII ... 文本，肉眼核对。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PIL import Image
from amta.typeset.typeset_render import render_item

FONT = "C:/Windows/Fonts/msyh.ttc"
OUT = Path(r"workspace\touhou-getten-shinchi\_probe")
OUT.mkdir(parents=True, exist_ok=True)

# 竖排
img = Image.new("RGB", (300, 700), "white")
render_item(img, "请让我留在您身边♡", FONT, [60, 40, 240, 660],
            stroke=0, preferred_direction="vertical")
img.save(OUT / "heart_vertical.png")

# 横排
img2 = Image.new("RGB", (700, 200), "white")
render_item(img2, "请让我留在您身边♡", FONT, [40, 40, 660, 160],
            stroke=0, preferred_direction="horizontal")
img2.save(OUT / "heart_horizontal.png")

# 竖排 ASCII 省略号
img3 = Image.new("RGB", (300, 500), "white")
render_item(img3, "八意大人...", FONT, [60, 40, 240, 460],
            stroke=0, preferred_direction="vertical")
img3.save(OUT / "dots_vertical.png")

print("saved to", OUT)
