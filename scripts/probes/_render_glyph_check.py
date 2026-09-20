"""一次性探针：验证 ❤(U+2665) / ︙(U+FE19) / ⋮(U+22EE) 是否真字形（非 .notdef）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PIL import Image, ImageDraw, ImageFont

FONT = "C:/Windows/Fonts/msyh.ttc"
OUT = Path(r"workspace\touhou-getten-shinchi\_probe")
OUT.mkdir(parents=True, exist_ok=True)

font = ImageFont.truetype(FONT, 60)
# 横向排开：每个候选字符一格，看哪个是真字形
cands = [("\u2661", "white_heart"), ("\u2665", "black_heart"),
         ("\uFE19", "vert_ellipsis"), ("\u22EE", "vdots"),
         ("\u2026", "horiz_ellipsis")]
img = Image.new("RGB", (len(cands) * 100, 120), "white")
d = ImageDraw.Draw(img)
for i, (ch, _) in enumerate(cands):
    d.text((i * 100 + 20, 30), ch, font=font, fill="black")
img.save(OUT / "glyph_check.png")
print("order:", [n for _, n in cands])
