"""Probe: find a text that produces a column-end comma with the render test bbox."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PIL import Image
from amta.typeset.typeset_render import render_item

FONT = "C:/Windows/Fonts/msyh.ttc"
texts = [
    "他说，今天不去了，明天再说吧，后天也许去，大后天也不一定",
    "你好，世界，你好，世界，你好，世界，你好，世界",
    "而且漫画家是一种职业，在幻想乡靠它谋生很难哦，真的",
    "仙人风范，端庄贤淑，温婉可人，落落大方，真是个好姑娘",
]
for t in texts:
    img = Image.new("RGB", (400, 900), "white")
    r = render_item(img, t, FONT, [100, 100, 240, 700], stroke=0,
                    preferred_direction="vertical")
    ends = [c.endswith("，") for c in r["lines"]]
    print(f"  fs={r['font_size']} lines={r['lines']} comma_end={ends}")
