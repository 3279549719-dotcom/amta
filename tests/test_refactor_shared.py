"""geometry.bbox 优先级 + images.crop_with_pad 确定性测试。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.common import geometry, images


class GeometryBboxPriorityTest(unittest.TestCase):
    def test_bbox_field_wins_over_transform(self):
        block = {"bbox": [1, 2, 3, 4], "transform": {"x": 10, "y": 20, "w": 30, "h": 40}}
        self.assertEqual(geometry.bbox_from_block(block), [1.0, 2.0, 3.0, 4.0])

    def test_transform_fallback_unchanged(self):
        block = {"transform": {"x": 10, "y": 20, "w": 30, "h": 40}}
        self.assertEqual(geometry.bbox_from_block(block), [10.0, 20.0, 40.0, 60.0])


class ImagesTest(unittest.TestCase):
    def test_crop_with_pad_clamps_bounds(self):
        from PIL import Image

        img = Image.new("RGB", (100, 100), "white")
        src = Path(self._testMethodName + ".jpg")  # 不落盘：直接测越界框
        # 越界 bbox：pad 后超出图宽 → 应被 clamp 且保存成功
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "p.jpg"
            img.save(src)
            dest = Path(td) / "crop.png"
            self.assertTrue(images.crop_with_pad(src, [90, 90, 200, 200], dest, pad=8))
            self.assertTrue(dest.exists())

    def test_crop_with_pad_rejects_empty_box(self):
        import tempfile

        from PIL import Image

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "p.jpg"
            Image.new("RGB", (100, 100), "white").save(src)
            dest = Path(td) / "crop.png"
            # 越界空框（pad 后 x1 <= x0）：不写文件
            self.assertFalse(images.crop_with_pad(src, [200, 200, 210, 220], dest))
            self.assertFalse(dest.exists())

if __name__ == "__main__":
    unittest.main()
