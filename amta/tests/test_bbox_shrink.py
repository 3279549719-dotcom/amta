"""气泡框智能收缩测试：detect框比气泡大时，收缩到气泡实际边界。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw

from amta.common.geometry import shrink_bubble_bbox


def test_shrink_bbox_wider_than_bubble():
    """detect框比气泡大时，应收缩到气泡边界线内侧。"""
    # 创建一个 300x300 的图，白色背景，中间有一个带黑色边界的白色气泡
    img = Image.new("RGB", (300, 300), "white")
    draw = ImageDraw.Draw(img)
    # 画带黑色边界的气泡（边界线宽3）
    draw.rectangle([50, 50, 250, 250], fill="white", outline="black", width=3)
    # 气泡内画文字
    draw.text((80, 100), "测试", fill="black")
    # detect 框比气泡大（超出气泡边界）
    bbox = [30, 30, 270, 270]
    result = shrink_bubble_bbox(img, bbox)
    # 收缩后的框应该在气泡边界线内侧（53-247左右）
    assert result[0] >= 45, f"左边界应收缩到气泡边界附近，当前{result[0]}"
    assert result[2] <= 255, f"右边界应收缩到气泡边界附近，当前{result[2]}"
    assert result[1] >= 45, f"上边界应收缩到气泡边界附近，当前{result[1]}"
    assert result[3] <= 255, f"下边界应收缩到气泡边界附近，当前{result[3]}"


def test_shrink_bbox_already_accurate():
    """detect框已经在气泡内时，不应过度收缩。"""
    img = Image.new("RGB", (300, 300), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 50, 250, 250], fill="white", outline="black", width=3)
    draw.text((80, 100), "测试文字内容", fill="black")
    # detect 框已经在气泡内（不包含边界线）
    bbox = [60, 60, 240, 240]
    result = shrink_bubble_bbox(img, bbox)
    # 不应过度收缩，框的面积不应小于原框的 60%
    orig_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    new_area = (result[2] - result[0]) * (result[3] - result[1])
    assert new_area > orig_area * 0.6, f"不应过度收缩，原面积{orig_area}，新面积{new_area}"


def test_shrink_bbox_returns_list():
    """返回值应该是4元素列表。"""
    img = Image.new("RGB", (100, 100), "white")
    bbox = [10, 10, 90, 90]
    result = shrink_bubble_bbox(img, bbox)
    assert isinstance(result, list)
    assert len(result) == 4
