"""一次性探针：对比候选字体里 ♡ 的实际长相，挑和微软雅黑最搭的。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PIL import Image, ImageDraw, ImageFont

CANDS = [
    ("C:/Windows/Fonts/msyh.ttc", "msyh(主,方框)"),
    ("C:/Windows/Fonts/NotoSansSC-VF.ttf", "NotoSansSC"),
    ("C:/Windows/Fonts/msgothic.ttc", "msgothic"),
    ("C:/Windows/Fonts/YuGothR.ttc", "YuGothR"),
    ("C:/Windows/Fonts/BIZ-UDGothicR.ttc", "BIZ-UDGothic"),
]
SIZE = 72
CELL = 110
img = Image.new("RGB", (len(CANDS) * CELL, CELL + 40), "white")
d = ImageDraw.Draw(img)
for i, (p, label) in enumerate(CANDS):
    try:
        f = ImageFont.truetype(p, SIZE)
        d.text((i * CELL + 25, 10), "\u2661", font=f, fill="black")
    except Exception as e:
        d.text((i * CELL + 5, 10), f"ERR", fill="red")
    d.text((i * CELL + 5, CELL + 15), label, fill="black")
img.save(r"workspace\touhou-getten-shinchi\_probe\heart_candidates.png")
print("order:", [c[1] for c in CANDS])
