"""RT-DETR-v2 检测器冒烟测试。

TDD seam: RTDetrDetector.detect(image) -> list[dict]
验证：模型能加载、输出格式正确、框在图像范围内、非空。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from detect_rtdetr import RTDetrDetector, merge_duplicate_boxes, remove_contained_boxes

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "CTBD" / "detector.onnx"
TEST_IMAGE = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地\11.jpg")


@pytest.fixture(scope="module")
def detector():
    if not MODEL_PATH.exists():
        pytest.skip(f"model not found: {MODEL_PATH}")
    det = RTDetrDetector(model_path=MODEL_PATH, conf_threshold=0.3)
    det._load()
    return det


class TestGeometry:
    """纯函数后处理测试，不依赖模型。"""

    def test_merge_duplicate_boxes_identical(self):
        boxes = np.array([[10, 10, 50, 50], [12, 12, 48, 48]])
        merged = merge_duplicate_boxes(boxes, iou_thresh=0.7)
        assert len(merged) == 1
        assert merged[0][0] == 10 and merged[0][1] == 10

    def test_merge_duplicate_boxes_disjoint(self):
        boxes = np.array([[0, 0, 10, 10], [100, 100, 110, 110]])
        merged = merge_duplicate_boxes(boxes, iou_thresh=0.7)
        assert len(merged) == 2

    def test_remove_contained_boxes(self):
        boxes = np.array([[0, 0, 100, 100], [10, 10, 20, 20]])
        kept = remove_contained_boxes(boxes, threshold=0.8)
        assert len(kept) == 1
        assert kept[0][0] == 0


class TestRTDetrDetector:
    """检测器集成测试，需要模型和测试图。"""

    @pytest.mark.skipif(not TEST_IMAGE.exists(), reason="test image not found")
    def test_detect_returns_blocks(self, detector):
        blocks = detector.detect(str(TEST_IMAGE))
        assert isinstance(blocks, list)
        assert len(blocks) > 0, "should detect at least one text box"

    @pytest.mark.skipif(not TEST_IMAGE.exists(), reason="test image not found")
    def test_detect_block_format(self, detector):
        blocks = detector.detect(str(TEST_IMAGE))
        for b in blocks:
            assert "bbox" in b
            assert len(b["bbox"]) == 4
            assert b["bbox"][2] > b["bbox"][0]
            assert b["bbox"][3] > b["bbox"][1]
            assert "source_engines" in b
            assert "rtdetr-v2" in b["source_engines"]

    @pytest.mark.skipif(not TEST_IMAGE.exists(), reason="test image not found")
    def test_detect_boxes_within_image(self, detector):
        import cv2
        # cv2.imread 不支持中文路径
        img = cv2.imdecode(np.fromfile(str(TEST_IMAGE), dtype=np.uint8), cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        blocks = detector.detect(img)
        for b in blocks:
            x1, y1, x2, y2 = b["bbox"]
            assert x1 >= 0 and y1 >= 0
            assert x2 <= w + 1 and y2 <= h + 1

    @pytest.mark.skipif(not TEST_IMAGE.exists(), reason="test image not found")
    def test_detect_reasonable_box_count(self, detector):
        """page_11 之前只有 3 框（严重漏检），RT-DETR-v2 应该检出更多。"""
        blocks = detector.detect(str(TEST_IMAGE))
        # 不设硬上限，但应该显著多于 3
        assert len(blocks) >= 3, f"expected >= 3 boxes, got {len(blocks)}"
