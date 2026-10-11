"""detect 单例测试 — 验证模型只加载一次。

TDD seam: detect_page() 内部不应每页新建 RTDetrDetector（导致重复加载 ONNX 模型）。
契约：同一进程内多次调用 detect_page，ort.InferenceSession 只被实例化一次。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from amta.stations.detect_station import detect_page, RTDetrDetector


@pytest.fixture
def fake_image(tmp_path: Path) -> Path:
    """造一张 100x100 的测试图。"""
    from PIL import Image
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    p = tmp_path / "test_page.jpg"
    img.save(p)
    return p


class TestDetectorSingleton:
    """验证 detect_page 复用同一个检测器实例，不重复加载模型。"""

    def test_detect_page_reuses_detector_instance(self, tmp_path: Path, fake_image: Path):
        """连续调用两次 detect_page，RTDetrDetector 只应被实例化一次。"""
        # 记录 RTDetrDetector 被实例化的次数
        init_count = 0
        original_init = RTDetrDetector.__init__

        def counting_init(self, *args, **kwargs):
            nonlocal init_count
            init_count += 1
            original_init(self, *args, **kwargs)

        # mock 掉 _detect_single，避免真的跑模型推理
        fake_boxes = np.array([[10, 10, 50, 50, 1, 0.9]])

        with patch.object(RTDetrDetector, "__init__", counting_init), \
             patch.object(RTDetrDetector, "_detect_single", return_value=fake_boxes), \
             patch.object(RTDetrDetector, "_load", return_value=None):

            out_dir = tmp_path / "out"
            out_dir.mkdir()

            # 第一次调用
            detect_page("test_work", fake_image, out_dir, page_idx=1)
            count_after_first = init_count

            # 第二次调用（不同页）
            detect_page("test_work", fake_image, out_dir, page_idx=2)
            count_after_second = init_count

        # 关键断言：第二次调用不应该新建实例
        assert count_after_first == 1, f"第一次调用后实例数应为1，实际{count_after_first}"
        assert count_after_second == 1, (
            f"第二次调用不应新建检测器实例！实例数从{count_after_first}变成{count_after_second}"
        )

    def test_detect_page_respects_conf_threshold(self, tmp_path: Path, fake_image: Path):
        """单例复用后，不同 conf_threshold 仍应生效（通过 detect() 参数传入）。"""
        fake_boxes = np.array([[10, 10, 50, 50, 1, 0.9]])
        captured_thresholds = []

        def fake_detect(self, image, conf_threshold=None):
            captured_thresholds.append(conf_threshold)
            return []

        with patch.object(RTDetrDetector, "_detect_single", return_value=fake_boxes), \
             patch.object(RTDetrDetector, "_load", return_value=None), \
             patch.object(RTDetrDetector, "detect", fake_detect):

            out_dir = tmp_path / "out"
            out_dir.mkdir()

            detect_page("test_work", fake_image, out_dir, page_idx=1, conf_threshold=0.5)
            detect_page("test_work", fake_image, out_dir, page_idx=2, conf_threshold=0.3)

        # 两次调用应分别传入各自的阈值
        assert captured_thresholds[0] == 0.5
        assert captured_thresholds[1] == 0.3
