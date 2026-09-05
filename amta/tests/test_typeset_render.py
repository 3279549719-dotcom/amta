import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image

from amta.typeset_render import render_item

FONT = "C:/Windows/Fonts/msyh.ttc"


def test_horizontal_render_centered_with_stroke():
    img = Image.new("RGB", (300, 200), "white")
    meta = render_item(img, "你好世界", FONT, [50, 50, 250, 150], stroke=2)
    assert meta["font_size"] >= 12
    assert meta["anchor_pos"] == [150, 100]  # 居中
    # 中心附近有非白色像素(文字已画)
    cx, cy = 150, 100
    inked = any(img.getpixel((x, y)) != (255, 255, 255)
                for x in range(cx - 30, cx + 30) for y in range(cy - 20, cy + 20))
    assert inked


def test_vertical_render_multi_column():
    """竖排多列渲染：窄长框+长文本应选竖排，多列从右到左排列。"""
    img = Image.new("RGB", (400, 1200), "white")
    text = "在那之后我的研究可能是因为八意大人开始插嘴的缘故进展得很顺利虽然很烦人但我忍耐了"
    meta = render_item(img, text, FONT, [100, 100, 307, 1054], stroke=0)
    assert meta["layout_direction"] == "vertical"
    assert meta["font_size"] >= 30, f"竖排字号应>=30，实际{meta['font_size']}"
    # 竖排多列：lines是列列表，总字数等于原文
    assert isinstance(meta["lines"], list)
    assert sum(len(col) for col in meta["lines"]) == len(text)
    # 中心列附近有墨迹
    cx = 203
    inked = any(img.getpixel((cx, y)) != (255, 255, 255) for y in range(200, 900))
    assert inked


def test_render_returns_meta_shape():
    img = Image.new("RGB", (100, 100), "white")
    meta = render_item(img, "短", FONT, [10, 10, 90, 90], stroke=0)
    assert set(meta) == {"layout_direction", "font_size", "lines", "anchor_pos", "preferred_direction"}
    assert meta["preferred_direction"] is None  # 接近方形的框推断为 None


def test_render_auto_infers_horizontal_for_wide_box():
    """横长框应自动推断为横排首选方向。"""
    img = Image.new("RGB", (500, 200), "white")
    meta = render_item(img, "比起那个还是研究研究", FONT, [50, 50, 430, 170], stroke=0)
    assert meta["preferred_direction"] == "horizontal"
    assert meta["layout_direction"] == "horizontal"


def test_render_auto_infers_vertical_for_tall_box():
    """窄长框应自动推断为竖排首选方向。"""
    img = Image.new("RGB", (200, 600), "white")
    meta = render_item(img, "冷静点并不是担心八意大人什么的", FONT, [50, 50, 150, 550], stroke=0)
    assert meta["preferred_direction"] == "vertical"
    assert meta["layout_direction"] == "vertical"
