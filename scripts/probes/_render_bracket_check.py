"""一次性探针：实测 msyh 对竖排括号 / 波浪的字形。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from PIL import Image, ImageDraw, ImageFont

FONT = "C:/Windows/Fonts/msyh.ttc"
SIZE = 60
CELL = 90
# 从左到右：横排括号 / 竖排括号Unicode / 波浪
cands = [
    ("（", "para open FF08"),
    ("）", "para close FF09"),
    ("︵", "vert open FE35"),
    ("︶", "vert close FE36"),
    ("〜", "wave dash 301C"),
    ("～", "fullwidth tilde FF5E"),
]
img = Image.new("RGB", (len(cands)*CELL, CELL+30), "white")
d = ImageDraw.Draw(img)
for i,(ch,label) in enumerate(cands):
    try:
        f = ImageFont.truetype(FONT, SIZE)
        d.text((i*CELL+15, 10), ch, font=f, fill="black")
    except Exception as e:
        d.text((i*CELL+5,10), "ERR", fill="red")
    d.text((i*CELL+5, CELL+12), label, fill="black")
img.save(r"workspace\touhou-getten-shinchi\_probe\bracket_check.png")
print([c[1] for c in cands])
