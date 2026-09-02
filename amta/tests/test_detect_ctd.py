"""CTD + DB 后处理检测器的 TDD 测试。

测试 seam: CtdDetector.detect(img_bgr) -> (blocks, time)
- blocks 格式: [{"bbox": [x1,y1,x2,y2], "source": "ctd-db", "quad": [[x,y],...]}]
- DB 后处理输出四边形框，比矩形 bbox 更精确
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "CTD" / "comictextdetector.pt.onnx"


class TestDBPostprocess:
    """DB 后处理纯函数测试（不依赖模型）。"""

    def test_seg_rep_extracts_boxes_from_probability_map(self):
        """SegDetectorRepresenter 能从概率图中提取四边形框。"""
        from detectors import _seg_rep_extract_boxes

        # 创建一个有白色矩形的概率图
        prob = np.zeros((256, 256), dtype=np.float32)
        prob[50:100, 50:200] = 0.9  # 文本区域

        boxes = _seg_rep_extract_boxes(prob, orig_h=256, orig_w=256, box_thresh=0.3)
        assert len(boxes) >= 1
        # 框应该覆盖文本区域
        x1, y1, x2, y2 = boxes[0]
        assert x1 <= 55 and y1 <= 55
        assert x2 >= 195 and y2 >= 95

    def test_seg_rep_filters_low_score(self):
        """低分区域被过滤。"""
        from detectors import _seg_rep_extract_boxes

        prob = np.zeros((256, 256), dtype=np.float32)
        prob[50:100, 50:200] = 0.2  # 低于阈值

        boxes = _seg_rep_extract_boxes(prob, orig_h=256, orig_w=256, box_thresh=0.6)
        assert len(boxes) == 0

    def test_quad_to_bbox(self):
        """四边形转外接矩形。"""
        from detectors import _quad_to_bbox

        quad = np.array([[10, 20], [50, 15], [52, 60], [8, 65]], dtype=np.float32)
        bbox = _quad_to_bbox(quad)
        assert bbox == [8.0, 15.0, 52.0, 65.0]


@pytest.mark.skipif(not MODEL_PATH.exists(), reason=f"CTD model not found: {MODEL_PATH}")
class TestCtdDetector:
    """CTD 检测器集成测试（依赖模型文件）。"""

    def test_detector_loads(self):
        """检测器能成功加载模型。"""
        from detectors import CtdDetector
        det = CtdDetector(model_path=MODEL_PATH)
        assert det._impl._net is not None

    def test_detector_returns_blocks(self):
        """检测器能从测试图中返回框。"""
        import cv2
        from detectors import CtdDetector

        det = CtdDetector(model_path=MODEL_PATH)
        # 创建一个有文字-like 图案的测试图
        img = np.ones((512, 512, 3), dtype=np.uint8) * 255
        cv2.putText(img, "TEST", (50, 250), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)

        blocks, elapsed = det.detect(img)
        assert isinstance(blocks, list)
        assert isinstance(elapsed, float)
        # 不一定能检测到合成文字，但至少不崩溃
        for b in blocks:
            assert "bbox" in b
            assert len(b["bbox"]) == 4
            assert b["source"] == "ctd-db"

    def test_detector_handles_vertical_image(self):
        """检测器能处理高瘦图（漫画常见比例）。"""
        import cv2
        from detectors import CtdDetector

        det = CtdDetector(model_path=MODEL_PATH)
        img = np.ones((1024, 768, 3), dtype=np.uint8) * 255
        blocks, _ = det.detect(img)
        assert isinstance(blocks, list)
