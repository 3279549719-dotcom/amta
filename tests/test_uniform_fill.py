"""均匀背景分流测试：纯白泡直接填色，复杂背景送 LaMa。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
from PIL import Image, ImageDraw

from amta.inpaint.inpaint_station import _route_by_uniformity


def test_white_bubble_direct_fill():
    """纯白气泡（黑字）：直接填白，不进 LaMa。"""
    img = Image.new("RGB", (200, 200), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 40), "あいう", fill="black")
    bbox = [20, 20, 180, 120]
    result, complex_boxes = _route_by_uniformity(img, [bbox])
    # 白泡：std 低，应该直接填，不进 LaMa
    assert len(complex_boxes) == 0, f"白泡不该进 LaMa，实际 {len(complex_boxes)}"
    # 文字位置应该变白
    arr = np.array(result)
    assert arr[50, 45].mean() > 200, "文字应被填白"


def test_complex_background_goes_lama():
    """网点/纹理背景：送 LaMa。"""
    # 模拟网点背景：随机噪点
    rng = np.random.RandomState(42)
    bg = rng.randint(100, 200, (200, 200), dtype=np.uint8)
    img = Image.fromarray(np.stack([bg]*3, axis=-1))
    d = ImageDraw.Draw(img)
    d.text((40, 40), "あいう", fill="black")
    bbox = [20, 20, 180, 120]
    _, complex_boxes = _route_by_uniformity(img, [bbox])
    # 噪点背景：std 高，应该送 LaMa
    assert len(complex_boxes) == 1, f"纹理背景应送 LaMa，实际 {len(complex_boxes)}"


def test_dark_hair_preserved():
    """黑发区域（暗背景）：直接填黑，不洗灰。"""
    img = Image.new("RGB", (200, 200), (30, 30, 30))
    d = ImageDraw.Draw(img)
    d.text((40, 40), "あいう", fill="white")
    bbox = [20, 20, 180, 120]
    result, complex_boxes = _route_by_uniformity(img, [bbox])
    # 纯色暗背景：直接填暗，不进 LaMa
    assert len(complex_boxes) == 0
    # 背景应该还是暗的（没被洗灰）
    arr = np.array(result)
    assert arr[100, 100].mean() < 60, "暗背景不该被洗灰"
