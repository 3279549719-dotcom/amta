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
    """CTD (ComicTextDetector) ONNX 检测器（方案 B）。

    manga-image-translator 的核心检测器，1024 输入，DB 后处理。
    简化版：单尺度推理 + 轮廓检测提取框。
    """
    name = "ctd-onnx"

    def __init__(self, model_path: Path | str | None = None, input_size: int = 1024,
                 box_threshold: float = 0.6, text_threshold: float = 0.3):
        self.model_path = Path(model_path) if model_path else ROOT / "models" / "CTD" / "comictextdetector.pt.onnx"
        self.input_size = input_size
        self.box_threshold = box_threshold
        self.text_threshold = text_threshold
        self._net = None
        self._load()

    def _load(self):
        if not self.model_path.exists():
            raise FileNotFoundError(f"CTD model not found: {self.model_path}")
        self._net = cv2.dnn.readNetFromONNX(str(self.model_path))
        self._net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self._net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

    def _preprocess(self, img_bgr: np.ndarray) -> tuple[np.ndarray, float, float]:
        """letterbox 到 input_size，返回 (input_tensor, ratio_w, ratio_h)。"""
        h, w = img_bgr.shape[:2]
        scale = min(self.input_size / h, self.input_size / w)
        new_h, new_w = int(h * scale), int(w * scale)
        resized = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        # pad to square
        pad_h = self.input_size - new_h
        pad_w = self.input_size - new_w
        padded = cv2.copyMakeBorder(resized, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=(114, 114, 114))
        # BGR -> RGB, normalize
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        blob = cv2.dnn.blobFromImage(rgb, 1.0 / 255.0, (self.input_size, self.input_size), swapRB=False)
        ratio_w = w / new_w if new_w > 0 else 1.0
        ratio_h = h / new_h if new_h > 0 else 1.0
        return blob, ratio_w, ratio_h

    def _detect(self, img_bgr: np.ndarray) -> list[list[float]]:
        h_orig, w_orig = img_bgr.shape[:2]
        blob, ratio_w, ratio_h = self._preprocess(img_bgr)
        self._net.setInput(blob)
        # CTD ONNX 输出: [mask, lines] 或类似
        outputs = self._net.forward(self._net.getUnconnectedOutLayersNames())
        # 找到 mask 输出（概率图）
        mask = None
        for out in outputs:
            if out.ndim == 4 and out.shape[1] in (1, 2):
                mask = out[0, 0] if out.shape[1] == 1 else out[0, 0]
                break
        if mask is None:
            # 尝试第二个输出
            for out in outputs:
                if out.ndim == 4:
                    mask = out[0, 0]
                    break
        if mask is None:
            return []
        # 裁剪掉 padding 区域
        h, w = mask.shape
        scale = min(self.input_size / h_orig, self.input_size / w_orig)
        new_h = int(h_orig * scale)
        new_w = int(w_orig * scale)
        mask_cropped = mask[:new_h, :new_w]
        # 阈值化
        binary = (mask_cropped > self.text_threshold).astype(np.uint8) * 255
        # 形态学操作
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        binary = cv2.dilate(binary, kernel, iterations=1)
        # 轮廓检测
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            area = bw * bh
            if area < 50:  # 过滤噪点
                continue
            # 映射回原图坐标
            x1 = x / new_w * w_orig
            y1 = y / new_h * h_orig
            x2 = (x + bw) / new_w * w_orig
            y2 = (y + bh) / new_h * h_orig
            boxes.append([x1, y1, x2, y2])
        return boxes
