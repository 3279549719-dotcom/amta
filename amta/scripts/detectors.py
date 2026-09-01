"""检测器统一接口 — 所有方案 A/B/C 的检测器都实现 detect(img_bgr) -> blocks。

blocks 格式: [{"bbox": [x1,y1,x2,y2], "source": "detector_name", ...}]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCRIPT_DIR))


class Detector:
    """检测器基类。子类实现 _detect(img_bgr) -> list[bbox]。"""
    name: str = "base"

    def detect(self, img_bgr: np.ndarray) -> tuple[list[dict], float]:
        """返回 (blocks, detect_time_sec)。blocks 含 bbox + source。"""
        t0 = time.perf_counter()
        boxes = self._detect(img_bgr)
        elapsed = time.perf_counter() - t0
        blocks = []
        for i, box in enumerate(boxes):
            x1, y1, x2, y2 = [float(v) for v in box]
            if x2 - x1 < 3 or y2 - y1 < 3:
                continue
            blocks.append({"bbox": [x1, y1, x2, y2], "source": self.name, "region_id": f"r{i:02d}"})
        return blocks, elapsed

    def _detect(self, img_bgr: np.ndarray) -> list[list[float]]:
        raise NotImplementedError


class BaselineDetector(Detector):
    """从 backup 加载现有 4 引擎并集结果（历史数据，不实时检测）。"""
    name = "baseline-4engine"

    def __init__(self, backup_dir: Path | str, page_num: int):
        self.backup_dir = Path(backup_dir)
        self.page_num = page_num

    def detect(self, img_bgr: np.ndarray) -> tuple[list[dict], float]:
        import json
        path = self.backup_dir / f"page_{self.page_num}_detection.json"
        if not path.exists():
            return [], 0.0
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        blocks = []
        for i, b in enumerate(d.get("blocks", [])):
            bb = b.get("bbox")
            if bb and len(bb) == 4:
                blocks.append({"bbox": [float(v) for v in bb], "source": self.name, "region_id": f"r{i:02d}"})
        return blocks, 0.0


class RTDetrDetector(Detector):
    """RT-DETR-v2 ONNX 检测器（方案 C）。从 detect_rtdetr.py 导入。"""
    name = "rtdetr-v2"

    def __init__(self, conf_threshold: float = 0.3):
        from detect_rtdetr import RTDetrDetector as _Impl
        self._impl = _Impl(conf_threshold=conf_threshold)
        self._impl._load()

    def _detect(self, img_bgr: np.ndarray) -> list[list[float]]:
        blocks = self._impl.detect(img_bgr)
        return [b["bbox"] for b in blocks]


class KoharuSingleDetector(Detector):
    """koharu 单引擎检测器（方案 A）。通过 koharu REST API 调用指定引擎。"""
    name = "koharu-single"

    def __init__(self, engine: str = "comic-text-detector", host: str = "127.0.0.1", port: int = 4000):
        from amta.koharu_client import KoharuClient
        from amta.runner import run_all_pages, compact_blocks
        self.engine = engine
        self.name = f"koharu-{engine}"
        self.client = KoharuClient(host=host, port=port)
        self.client.wait_server(timeout=60)
        self._run_all_pages = run_all_pages
        self._compact = compact_blocks
        self._steps = {engine: [engine]}
        self._FIELDS = ("node_id", "bbox", "bubble_type", "text")

    def _detect(self, img_bgr: np.ndarray) -> list[list[float]]:
        # koharu 需要文件路径，写临时文件
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
        cv2.imwrite(tmp_path, img_bgr)
        try:
            results = self._run_all_pages(
                self.client, [Path(tmp_path)], self._steps,
                prefix="ab-test", timeout=300, label="ab-detect",
            )
            page_key = next(iter(results))
            per_engine = results[page_key]["engines"]
            blks = per_engine.get(self.engine, [])
            comp = self._compact(blks, self._FIELDS, source_engine=self.engine)
            return [b["bbox"] for b in comp]
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class CtdDetector(Detector):
    """CTD + DB 后处理检测器（方案 B）。

    包装 ctd_detector.CtdDetector，输出四边形框（精确）+ 外接矩形。
    模型: comictextdetector.pt.onnx (YOLOv5 + UNet + DBNet)
    """
    name = "ctd-db"

    def __init__(self, model_path: Path | str | None = None, input_size: int = 1024,
                 box_thresh: float = 0.6, **kwargs):
        from ctd_detector import CtdDetector as _Impl
        self._impl = _Impl(model_path=model_path, input_size=input_size, box_thresh=box_thresh)

    def detect(self, img_bgr: np.ndarray) -> tuple[list[dict], float]:
        return self._impl.detect(img_bgr)


# 导出工具函数供测试使用
from ctd_detector import seg_rep_extract_boxes as _seg_rep_extract_boxes, quad_to_bbox as _quad_to_bbox  # noqa: E402
