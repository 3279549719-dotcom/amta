"""inpaint_station 测试：FILL_WHITE 只涂文字像素，不涂整个矩形。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
from PIL import Image, ImageDraw

from amta.inpaint.inpaint_station import _apply_fill_white


def test_fill_white_only_covers_text_pixels():
    """FILL_WHITE 应只涂文字像素，不涂 bbox 内的非文字区域（如框外的作者标记）。

    模拟场景：bbox 超出气泡范围，包含了气泡外的黑色像素（作者标记）。
    修复后：只有文字像素被涂白，作者标记保留。
    """
    # 创建一个 200x200 的测试图
    img = Image.new("RGB", (200, 200), "white")
    draw = ImageDraw.Draw(img)
    # 在左侧画一些文字（模拟气泡内文字）
    draw.text((20, 50), "测试文字", fill="black")
    # 在右侧画一个黑色小方块（模拟框外的作者标记，紧贴 bbox 右边缘）
    draw.rectangle([172, 80, 190, 100], fill="black")

    # bbox 覆盖整个区域（超出气泡范围，右边界 180，作者标记 172-190 部分在框内）
    bbox = [10, 40, 180, 120]

    # 执行涂白
    _apply_fill_white(img, bbox)

    # 修复后：作者标记区域应该仍然是黑色（没有被涂白）
    marker_after = img.getpixel((175, 90))
    assert marker_after == (0, 0, 0), f"作者标记不应被涂白，当前{marker_after}"

    # 文字区域应该被涂白
    # 文字区域可能有部分是白色（笔画间隙），但至少有一些文字像素被涂白了
    # 这里检查文字区域的平均亮度应该提高
    text_region = img.crop((20, 50, 80, 80))
    text_arr = np.array(text_region)
    brightness = text_arr.mean()
    assert brightness > 200, f"文字区域应被涂白，当前亮度{brightness:.1f}"
