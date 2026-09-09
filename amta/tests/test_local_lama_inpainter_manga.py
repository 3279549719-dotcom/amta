"""TDD 切片2: LocalLamaInpainter 支持 model_type=lama-manga。

验证:
1. LocalLamaInpainter(model_type="lama-manga") 能加载模型
2. inpaint() 输出尺寸正确
3. 模型类型属性正确
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from amta.inpaint.local_lama_inpainter import LocalLamaInpainter


def make_test_image(size: int = 256) -> Image.Image:
    """生成带白色方块的测试图（模拟文字区域）。"""
    arr = np.random.randint(50, 200, (size, size, 3), dtype=np.uint8)
    arr[100:150, 100:150] = 255  # 白色方块模拟文字
    return Image.fromarray(arr)


def make_test_mask(size: int = 256) -> Image.Image:
    """生成对应白色方块的 mask。"""
    arr = np.zeros((size, size), dtype=np.uint8)
    arr[100:150, 100:150] = 255
    return Image.fromarray(arr)


def test_load_lama_manga():
    """LocalLamaInpainter(model_type='lama-manga') 能加载模型。"""
    inpainter = LocalLamaInpainter(device="cpu", model_type="lama-manga")
    assert inpainter.model_type == "lama-manga"
    assert inpainter.model is not None
    assert inpainter.load_time_s > 0


def test_inpaint_output_shape():
    """inpaint() 输出尺寸与输入一致。"""
    inpainter = LocalLamaInpainter(device="cpu", model_type="lama-manga")
    img = make_test_image(256)
    mask = make_test_mask(256)
    result = inpainter.inpaint(img, mask)
    assert result.size == img.size, f"expected {img.size}, got {result.size}"
    assert result.mode == "RGB"


def test_inpaint_non_square():
    """inpaint() 支持非正方形输入。"""
    inpainter = LocalLamaInpainter(device="cpu", model_type="lama-manga")
    img = make_test_image(320)
    img = img.crop((0, 0, 320, 200))  # 320x200 非正方形
    mask = make_test_mask(320).crop((0, 0, 320, 200))
    result = inpainter.inpaint(img, mask)
    assert result.size == img.size, f"expected {img.size}, got {result.size}"


def test_model_type_default():
    """默认 model_type 是 big-lama（向后兼容）。"""
    # 不实际加载 big-lama，只检查默认值
    import inspect
    sig = inspect.signature(LocalLamaInpainter.__init__)
    default = sig.parameters.get("model_type")
    assert default is not None, "model_type parameter should exist"
    assert default.default == "big-lama", f"expected default 'big-lama', got {default.default}"


if __name__ == "__main__":
    tests = [
        test_load_lama_manga,
        test_inpaint_output_shape,
        test_inpaint_non_square,
        test_model_type_default,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS: {t.__name__}")
        except Exception as e:
            print(f"  FAIL: {t.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{'='*40}")
    print(f"Results: {len(tests)-failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
