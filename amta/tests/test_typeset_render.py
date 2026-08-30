import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image

from amta.typeset_render import render_item

FONT = "C:/Windows/Fonts/msyh.ttc"


def test_horizontal_render_centered_with_stroke():
    img = Image.new("RGB", (300, 200), "white")
    meta = render_item(img, "你好世界", FONT, [50, 50, 250, 150], "horizontal", stroke=2)
    assert meta["font_size"] >= 12
    assert meta["anchor_pos"] == [150, 100]  # 居中
    assert meta["layout_direction"] == "horizontal"
    # 中心附近有非白色像素(文字已画)
    cx, cy = 150, 100
    inked = any(img.getpixel((x, y)) != (255, 255, 255)
                for x in range(cx - 30, cx + 30) for y in range(cy - 20, cy + 20))
    assert inked


def test_vertical_render_single_column():
    img = Image.new("RGB", (200, 300), "white")
    meta = render_item(img, "月都", FONT, [80, 30, 120, 270], "vertical", stroke=0)
    assert meta["layout_direction"] == "vertical"
    assert meta["lines"] == ["月都"]
    # 竖排: 中心列有墨迹
    px = 100
    inked = any(img.getpixel((px, y)) != (255, 255, 255) for y in range(30, 270))
    assert inked
    # 两个字符应纵向分布(上下都有墨迹)
    upper = any(img.getpixel((px, y)) != (255, 255, 255) for y in range(30, 140))
    lower = any(img.getpixel((px, y)) != (255, 255, 255) for y in range(150, 270))
    assert upper and lower


def test_render_returns_meta_shape():
    img = Image.new("RGB", (100, 100), "white")
    meta = render_item(img, "短", FONT, [10, 10, 90, 90], "horizontal", stroke=0)
    assert set(meta) == {"layout_direction", "font_size", "lines", "anchor_pos"}
