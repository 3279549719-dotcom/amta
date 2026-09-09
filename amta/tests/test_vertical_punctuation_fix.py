"""竖排标点修复测试：！？并排、省略号位置、文字不出框。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image
from amta.typeset.typeset_render import render_item

FONT = "C:/Windows/Fonts/msyh.ttc"


def _ink_bbox(img, x1, y1, x2, y2):
    """返回区域内墨迹的边界框 (min_x, min_y, max_x, max_y)。"""
    xs, ys = [], []
    for x in range(x1, x2):
        for y in range(y1, y2):
            if img.getpixel((x, y)) != (255, 255, 255):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def test_vertical_double_exclamation_side_by_side():
    """竖排中连续！！应左右并排在同一行，而非上下排列。"""
    img = Image.new("RGB", (300, 600), "white")
    bbox = [80, 80, 220, 520]
    text = "啊！！"
    result = render_item(img, text, FONT, bbox, stroke=0, preferred_direction="vertical")
    assert result["layout_direction"] == "vertical"
    # 上下排列时：3个字符占3行，墨迹高度约=3*行高
    # 并排时：啊占1行，！！并排占1行，共2行，墨迹高度约=2*行高
    ink = _ink_bbox(img, *bbox)
    assert ink is not None
    ink_h = ink[3] - ink[1]
    font_size = result["font_size"]
    lh = font_size * 1.2
    # 并排时只有2行，高度应 < 2.5 * lh
    # 上下排列时有3行，高度约 3 * lh
    assert ink_h < 2.5 * lh, (
        f"！！应并排(2行)，墨迹高度应<{2.5*lh:.0f}，实际{ink_h}"
    )


def test_vertical_ellipsis_in_same_column():
    """竖排省略号旋转后应在同一列内，不偏到左边。"""
    img = Image.new("RGB", (300, 800), "white")
    bbox = [80, 80, 220, 720]
    text = "测试省略号……"
    result = render_item(img, text, FONT, bbox, stroke=0, preferred_direction="vertical")
    assert result["layout_direction"] == "vertical"
    # 省略号在最后一列的最下方
    # 检查省略号区域的 x 坐标是否和其他字符重叠（同一列）
    # 找到所有墨迹的 x 坐标分布
    x_coords = []
    for x in range(bbox[0], bbox[2]):
        for y in range(bbox[1], bbox[3]):
            if img.getpixel((x, y)) != (255, 255, 255):
                x_coords.append(x)
    assert len(x_coords) > 50
    # 省略号偏左会导致 x 坐标分布出现两个明显分离的簇
    # 正常同一列：x 坐标标准差小
    x_mean = sum(x_coords) / len(x_coords)
    x_std = (sum((x - x_mean) ** 2 for x in x_coords) / len(x_coords)) ** 0.5
    font_size = result["font_size"]
    # 同一列内 x 标准差应 < 字号*0.6
    assert x_std < font_size * 0.6, (
        f"省略号偏左导致x标准差过大: {x_std:.1f} > {font_size*0.6:.1f}"
    )


def test_vertical_text_not_overflow_bbox():
    """竖排长文本不应超出 bbox 边界。"""
    img = Image.new("RGB", (400, 1000), "white")
    bbox = [100, 100, 300, 900]  # 宽200高800
    text = "那么丰酱我这就去给辉夜大人看这根羽毛那么就这样好的没问题"
    result = render_item(img, text, FONT, bbox, stroke=0, preferred_direction="vertical")
    assert result["layout_direction"] == "vertical"
    # 检查 bbox 外是否有墨迹
    # 检查 bbox 左右各 5 像素的边缘区域
    for x in range(bbox[0] - 3, bbox[0]):
        for y in range(bbox[1], bbox[3]):
            assert img.getpixel((x, y)) == (255, 255, 255), f"左侧出框 at ({x},{y})"
    for x in range(bbox[2], bbox[2] + 3):
        for y in range(bbox[1], bbox[3]):
            assert img.getpixel((x, y)) == (255, 255, 255), f"右侧出框 at ({x},{y})"
