import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image

from amta.typeset.typeset_render import render_item

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


def test_render_vertical_ellipsis_rotated():
    """竖排渲染时，省略号等横向标点应旋转90度绘制。"""
    from amta.typeset.typeset_render import render_item
    img = Image.new("RGB", (400, 800), "white")
    bbox = [100, 100, 300, 700]  # 窄长框 → 竖排
    text = "测试省略号……"
    result = render_item(img, text, "msyh.ttc", bbox, stroke=0,
                         preferred_direction="vertical")
    assert result["layout_direction"] == "vertical"
    # 验证图片不是全白（有内容被绘制）
    bbox_region = img.crop((100, 100, 300, 700))
    pixels = list(bbox_region.getdata())
    non_white = sum(1 for p in pixels if p != (255, 255, 255))
    assert non_white > 100  # 有足够多的文字像素


def test_render_vertical_dash_rotated():
    """竖排渲染时，破折号应旋转90度绘制。"""
    from amta.typeset.typeset_render import render_item
    img = Image.new("RGB", (400, 800), "white")
    bbox = [100, 100, 300, 700]
    text = "破折号测试——"
    result = render_item(img, text, "msyh.ttc", bbox, stroke=0,
                         preferred_direction="vertical")
    assert result["layout_direction"] == "vertical"
    bbox_region = img.crop((100, 100, 300, 700))
    pixels = list(bbox_region.getdata())
    non_white = sum(1 for p in pixels if p != (255, 255, 255))
    assert non_white > 100


def test_vertical_render_horizontally_centered():
    """竖排文字应在bbox内水平居中，墨迹x坐标均值接近bbox中心。"""
    img = Image.new("RGB", (400, 800), "white")
    bbox = [100, 100, 300, 700]  # 宽度200，中心x=200
    text = "测试文字居中对齐"
    result = render_item(img, text, FONT, bbox, stroke=0,
                         preferred_direction="vertical")
    assert result["layout_direction"] == "vertical"
    # 计算bbox内所有非白色像素的x坐标均值
    x_coords = []
    for x in range(100, 300):
        for y in range(100, 700):
            if img.getpixel((x, y)) != (255, 255, 255):
                x_coords.append(x)
    assert len(x_coords) > 100, "应有足够多的文字像素"
    x_mean = sum(x_coords) / len(x_coords)
    # 均值应在中心±15像素范围内（当前bug会偏左约col_width/2）
    assert abs(x_mean - 200) < 15, f"文字x均值{x_mean:.1f}偏离中心200太多"


def test_vertical_render_exclamation_rotated():
    """竖排渲染时，感叹号应旋转90度绘制（墨迹区域高>宽）。"""
    img = Image.new("RGB", (200, 400), "white")
    bbox = [50, 50, 150, 350]
    text = "！"  # 只渲染一个感叹号
    result = render_item(img, text, FONT, bbox, stroke=0,
                         preferred_direction="vertical")
    assert result["layout_direction"] == "vertical"
    # 找到墨迹区域的边界框
    non_white = []
    for x in range(50, 150):
        for y in range(50, 350):
            if img.getpixel((x, y)) != (255, 255, 255):
                non_white.append((x, y))
    assert len(non_white) > 20, "应有足够多的文字像素"
    xs = [p[0] for p in non_white]
    ys = [p[1] for p in non_white]
    ink_w = max(xs) - min(xs)
    ink_h = max(ys) - min(ys)
    # 旋转后的感叹号应该是垂直的：高度 > 宽度
    assert ink_h > ink_w, f"旋转后应垂直(高>宽)，实际宽={ink_w} 高={ink_h}"
