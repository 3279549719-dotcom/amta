"""detect 工位库函数 — RT-DETR-v2 漫画文本检测器（ONNX，CPU 友好）。

从 scripts/detect_rtdetr.py + scripts/01_detect.py 抽取合并：
- RTDetrDetector: ONNX 推理（640x640 输入，ogkalu/comic-text-and-bubble-detector）
- detect_page: 单页检测 → detection.json（doc 信封格式）

用法:
    from amta.stations.detect_station import detect_page
    doc = detect_page(work_id, raw_page, out_dir, page_idx=11, conf_threshold=0.5)
"""
from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import onnxruntime as ort

from amta.common.paths import write_json

# 项目根：src/amta/detect_station.py → 上溯三级到项目根
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_PATH = _PROJECT_ROOT / "models" / "CTBD" / "detector.onnx"


# ---- 几何工具 ----

def _iou(a: list[float], b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = a[:4]
    bx0, by0, bx1, by1 = b[:4]
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua > 0 else 0.0


def _area(b: list[float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _best_label_score(group: np.ndarray) -> tuple[int, float]:
    if group.shape[1] > 5:
        best_idx = int(np.argmax(group[:, 5]))
        return int(group[best_idx, 4]), float(group[best_idx, 5])
    return 1, 0.0


def merge_duplicate_boxes(boxes: np.ndarray, iou_thresh: float = 0.7) -> np.ndarray:
    if boxes is None or len(boxes) < 2:
        return boxes if boxes is not None else np.array([]).reshape(0, 6)
    n = len(boxes)
    adj = {i: [] for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if _iou(boxes[i], boxes[j]) >= iou_thresh:
                adj[i].append(j)
                adj[j].append(i)
    visited = set()
    components = []
    for i in range(n):
        if i not in visited:
            comp = []
            queue = [i]
            visited.add(i)
            while queue:
                curr = queue.pop(0)
                comp.append(curr)
                for nb in adj[curr]:
                    if nb not in visited:
                        visited.add(nb)
                        queue.append(nb)
            components.append(comp)
    merged = []
    for comp in components:
        cb = boxes[comp]
        label, score = _best_label_score(cb)
        merged.append([cb[:, 0].min(), cb[:, 1].min(), cb[:, 2].max(), cb[:, 3].max(), label, score])
    return np.array(merged)


def remove_contained_boxes(boxes: np.ndarray, threshold: float = 0.8) -> np.ndarray:
    if boxes is None or len(boxes) < 2:
        return boxes if boxes is not None else np.array([]).reshape(0, 6)
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    idxs = np.argsort(areas)[::-1]
    sorted_boxes = boxes[idxs]
    keep = []
    for box in sorted_boxes:
        x1, y1, x2, y2 = box[:4]
        area = (x2 - x1) * (y2 - y1)
        if area <= 0:
            continue
        is_contained = False
        for kept in keep:
            kx1, ky1, kx2, ky2 = kept[:4]
            ix1 = max(x1, kx1)
            iy1 = max(y1, ky1)
            ix2 = min(x2, kx2)
            iy2 = min(y2, ky2)
            iw = max(0, ix2 - ix1)
            ih = max(0, iy2 - iy1)
            if iw * ih / area >= threshold:
                is_contained = True
                break
        if not is_contained:
            keep.append(box)
    return np.array(keep) if keep else np.array([]).reshape(0, 6)


# ---- 瓦片化副引擎 ----

class TiledDetector:
    """瓦片化副引擎：把整图切成 cols×rows 网格（overlap 0.15），每块 640 推理，
    坐标映射回原图，NMS max-conf 合并同位置重复框，输出 conf>=conf_thresh 的框。

    主链（整图 640/0.5）之外的补漏引擎：小字/框外字在瓦片下 conf 显著提升。
    碎片（与主链框 coverage>=0.5）由调用方过滤。
    """

    OVERLAP = 0.15

    def __init__(self, detector: "RTDetrDetector", cols: int = 3, rows: int = 4,
                 conf_threshold: float = 0.3, nms_iou: float = 0.5):
        self.detector = detector
        self.cols = cols
        self.rows = rows
        self.conf_threshold = conf_threshold
        self.nms_iou = nms_iou

    def _detect(self, image: np.ndarray) -> np.ndarray:
        """单块推理，保持原始坐标（未映射）。"""
        # 临时降低 conf_threshold 以便收集低置信候选，由上层过滤
        old = self.detector.conf_threshold
        self.detector.conf_threshold = self.conf_threshold
        try:
            return self.detector._detect_single(image)
        finally:
            self.detector.conf_threshold = old

    def detect(self, image: np.ndarray) -> list[dict]:
        h, w = image.shape[:2]
        tile_w = w / self.cols
        tile_h = h / self.rows
        step_w = tile_w * (1 - self.OVERLAP)
        step_h = tile_h * (1 - self.OVERLAP)
        out: list[np.ndarray] = []
        for r in range(self.rows):
            for c in range(self.cols):
                x0 = max(0, int(c * step_w))
                y0 = max(0, int(r * step_h))
                x1 = min(w, int(x0 + tile_w))
                y1 = min(h, int(y0 + tile_h))
                tile = image[y0:y1, x0:x1].copy()
                dets = self._detect(tile)
                if dets.size == 0:
                    continue
                dets = dets.copy()
                dets[:, [0, 2]] += x0
                dets[:, [1, 3]] += y0
                out.append(dets)
        if not out:
            return []
        combined = np.vstack(out)
        return self._nms_max_conf(combined)

    def _nms_max_conf(self, dets: np.ndarray) -> list[dict]:
        """按 conf 降序，保留与已选框 IoU<nms_iou 的最高 conf 框（不合并 bbox）。"""
        if dets.size == 0:
            return []
        order = np.argsort(-dets[:, 5])
        keep: list[dict] = []
        suppressed: set[int] = set()
        for i in order:
            if i in suppressed:
                continue
            d = dets[i]
            keep.append({"bbox": [int(v) for v in d[:4]], "label": int(d[4]), "conf": float(d[5])})
            for j in order:
                if j in suppressed or j == i:
                    continue
                if _iou([int(v) for v in dets[i][:4]], [int(v) for v in dets[j][:4]]) >= self.nms_iou:
                    suppressed.add(j)
        return keep


def _coverage_of(c: list[float], main_boxes: list[list[float]]) -> float:
    """C 被主链任一框覆盖的最大比例 coverage = inter / area(C)。"""
    ac = _area(c)
    if ac <= 0:
        return 0.0
    return max((_inter_area(c, m) / ac for m in main_boxes), default=0.0)


def _inter_area(a: list[float], b: list[float]) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy


def merge_tiled_new_boxes(main_boxes: list[dict], tiled_boxes: list[dict],
                          coverage_thresh: float = 0.5, conf_thresh: float = 0.5,
                          min_side: int = 5) -> list[dict]:
    """合并主链与瓦片化副引擎结果：
    - 主链全保留
    - 副引擎只保留 conf>=conf_thresh 且与主链任一框 coverage<coverage_thresh 的框（真新增）
    - 碎片（coverage>=threshold，含被主链大框包含的）直接丢弃
    """
    main_bboxes = [b["bbox"] for b in main_boxes]
    merged = list(main_boxes)
    for tb in tiled_boxes:
        if tb["conf"] < conf_thresh:
            continue
        x1, y1, x2, y2 = tb["bbox"]
        if (x2 - x1) < min_side or (y2 - y1) < min_side:
            continue
        if _coverage_of(tb["bbox"], main_bboxes) >= coverage_thresh:
            continue  # 碎片：主链已覆盖
        merged.append({
            "bbox": [float(x1), float(y1), float(x2), float(y2)],
            "source_engines": ["rtdetr-v2-tiled"],
            "det_label": tb["label"],
            "region_id": f"t{len(merged):02d}",
            "confidence": round(tb["conf"], 4),
        })
    return merged


# ---- 图像切片器 ----

class ImageSlicer:
    def __init__(self, hw_ratio_thresh: float = 3.5, target_ratio: float = 3.0,
                 overlap: float = 0.2, min_slice_ratio: float = 0.7):
        self.hw_ratio_thresh = hw_ratio_thresh
        self.target_ratio = target_ratio
        self.overlap = overlap
        self.min_slice_ratio = min_slice_ratio

    def should_slice(self, image: np.ndarray) -> bool:
        h, w = image.shape[:2]
        return w > 0 and (h / w) > self.hw_ratio_thresh

    def _slice_params(self, h: int, w: int) -> tuple[int, int, int, int]:
        slice_w = w
        slice_h = max(1, int(slice_w * self.target_ratio))
        eff_h = max(1, int(slice_h * (1 - self.overlap)))
        num = math.ceil(h / eff_h) if eff_h > 0 else 1
        if num > 1 and slice_h > 0 and (h - (num - 1) * eff_h) / slice_h < self.min_slice_ratio:
            num -= 1
        return slice_w, slice_h, eff_h, max(1, num)

    def process(self, image: np.ndarray, detect_fn: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
        if not self.should_slice(image):
            return detect_fn(image)
        h, w = image.shape[:2]
        _, slice_h, eff_h, num = self._slice_params(h, w)
        all_boxes = []
        for i in range(num):
            start_y = i * eff_h
            end_y = h if i == num - 1 else min(start_y + slice_h, h)
            start_y = min(start_y, h - 1)
            end_y = max(start_y + 1, end_y)
            slice_img = image[start_y:end_y, 0:w].copy()
            boxes = detect_fn(slice_img)
            if boxes.size > 0:
                boxes = boxes.copy()
                boxes[:, [1, 3]] += start_y
                all_boxes.append(boxes)
        if not all_boxes:
            return np.array([])
        combined = np.vstack(all_boxes)
        return self._merge(combined, h)

    def _merge(self, boxes: np.ndarray, img_h: int) -> np.ndarray:
        if boxes.size < 2:
            return boxes
        bl = sorted(boxes.tolist(), key=lambda b: b[1])
        y_dist_thresh = 0.1 * img_h
        i = 0
        while i < len(bl):
            j = i + 1
            merged = False
            while j < len(bl):
                b1, b2 = bl[i], bl[j]
                if b2[1] > b1[3] + y_dist_thresh * 2:
                    break
                iou_val = _iou(b1, b2)
                a1, a2 = _area(b1), _area(b2)
                ix1 = max(b1[0], b2[0])
                iy1 = max(b1[1], b2[1])
                ix2 = min(b1[2], b2[2])
                iy2 = min(b1[3], b2[3])
                inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                contained = inter / min(a1, a2) >= 0.85 if min(a1, a2) > 0 else False
                if contained:
                    if a1 >= a2:
                        bl.pop(j)
                    else:
                        bl[i] = b2
                        bl.pop(j)
                        merged = True
                        break
                    continue
                if iou_val >= 0.5:
                    if a2 > a1:
                        bl[i] = b2
                    bl.pop(j)
                    merged = True
                    break
                y_dist = min(abs(b1[1] - b2[3]), abs(b1[3] - b2[1]))
                x_overlap = max(0, min(b1[2], b2[2]) - max(b1[0], b2[0]))
                min_w = min(b1[2] - b1[0], b2[2] - b2[0])
                x_ratio = x_overlap / min_w if min_w > 0 else 0
                size_ratio = min(a1, a2) / max(a1, a2) if max(a1, a2) > 0 else 0
                if y_dist < y_dist_thresh and x_ratio > 0.2 and size_ratio > 0.3:
                    merged_box = [min(b1[0], b2[0]), min(b1[1], b2[1]),
                                  max(b1[2], b2[2]), max(b1[3], b2[3])]
                    if len(b1) > 5 and len(b2) > 5:
                        best = b1 if b1[5] >= b2[5] else b2
                        merged_box.extend([best[4], best[5]])
                    m_area = (merged_box[2] - merged_box[0]) * (merged_box[3] - merged_box[1])
                    if m_area <= 3 * max(a1, a2):
                        bl[i] = merged_box
                        bl.pop(j)
                        merged = True
                        break
                j += 1
            if not merged:
                i += 1
        return np.array(bl) if bl else np.array([]).reshape(0, 6)


# ---- 主检测器 ----

class RTDetrDetector:
    def __init__(self, model_path: Path | str | None = None,
                 conf_threshold: float = 0.3, device: str = "cpu"):
        self.model_path = Path(model_path) if model_path else MODEL_PATH
        self.conf_threshold = conf_threshold
        self.device = device
        self._session: ort.InferenceSession | None = None
        self.slicer = ImageSlicer()

    def _load(self) -> None:
        if self._session is not None:
            return
        providers = ["CPUExecutionProvider"]
        if self.device.startswith("cuda"):
            try:
                available = ort.get_available_providers()
                if "CUDAExecutionProvider" in available:
                    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            except Exception:
                pass
        self._session = ort.InferenceSession(str(self.model_path), providers=providers)

    def _detect_single(self, image: np.ndarray) -> np.ndarray:
        self._load()
        assert self._session is not None
        h_orig, w_orig = image.shape[:2]
        resized = cv2.resize(image, (640, 640), interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        chw = rgb.transpose(2, 0, 1).astype(np.float32) / 255.0
        input_tensor = np.expand_dims(chw, axis=0)
        orig_sizes = np.array([[w_orig, h_orig]], dtype=np.int64)
        outputs = self._session.run(None, {
            "images": input_tensor,
            "orig_target_sizes": orig_sizes,
        })
        labels: np.ndarray = outputs[0]  # type: ignore[assignment]
        boxes: np.ndarray = outputs[1]  # type: ignore[assignment]
        scores: np.ndarray = outputs[2]  # type: ignore[assignment]
        text_dets = []
        for box, score, label in zip(boxes[0], scores[0], labels[0]):
            if score < self.conf_threshold:
                continue
            if label in (1, 2):
                x1, y1, x2, y2 = map(int, box)
                text_dets.append([x1, y1, x2, y2, int(label), float(score)])
        return np.array(text_dets) if text_dets else np.array([]).reshape(0, 6)

    def detect(self, image: str | Path | np.ndarray,
               conf_threshold: float | None = None) -> list[dict]:
        if conf_threshold is not None:
            self.conf_threshold = conf_threshold
        if isinstance(image, (str, Path)):
            img = cv2.imdecode(np.fromfile(str(image), dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise FileNotFoundError(f"Cannot read image: {image}")
        else:
            img = image
        t0 = time.perf_counter()
        boxes = self.slicer.process(img, self._detect_single)
        if boxes.size > 0:
            boxes = merge_duplicate_boxes(boxes, iou_thresh=0.7)
            boxes = remove_contained_boxes(boxes, threshold=0.8)
        elapsed = time.perf_counter() - t0
        blocks = []
        rid_counter = 0
        for box in boxes:
            x1, y1, x2, y2 = [int(v) for v in box[:4]]
            if (x2 - x1) < 5 or (y2 - y1) < 5:
                continue
            label = int(box[4]) if len(box) > 4 else 1
            score = float(box[5]) if len(box) > 5 else 0.0
            blocks.append({
                "bbox": [float(x1), float(y1), float(x2), float(y2)],
                "source_engines": ["rtdetr-v2"],
                "det_label": label,
                "region_id": f"r{rid_counter:02d}",
                "confidence": round(score, 4),
            })
            rid_counter += 1
        self._last_time = elapsed
        self._last_n = len(blocks)
        return blocks


# ---- 工位函数 ----

def detect_page(work_id: str, raw_page: Path, out_dir: Path, *,
                page_idx: int | None = None, conf_threshold: float = 0.5,
                tiling_enabled: bool = False, tiling_cols: int = 3, tiling_rows: int = 4,
                tiling_conf: float = 0.3, tiling_nms_iou: float = 0.5,
                coverage_thresh: float = 0.5, out_path: Path | None = None) -> dict:
    """单页检测：RT-DETR-v2（整图 640）→ 可选瓦片化副引擎补漏 → detection.json。

    - 主链：整图 conf_threshold（默认 0.5，ADR-Q1 甜点：+6真小字/0杂质/0额外时间），全保留
    - 副引擎（tiling_enabled=True，默认关闭）：cols×rows 网格，只保留 conf>=0.5 且
      与主链任一框 coverage<coverage_thresh 的框（真新增），碎片被覆盖即丢弃
    """
    if page_idx is None:
        page_idx = int(raw_page.stem)
    page = f"page_{page_idx}"
    det = RTDetrDetector(conf_threshold=conf_threshold)
    t0 = time.time()
    blocks = det.detect(str(raw_page))
    per_engine = {"rtdetr-v2": len(blocks)}

    if tiling_enabled:
        img = cv2.imdecode(np.fromfile(str(raw_page), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"imdecode 失败，无法读入原图: {raw_page}")
        tiled = TiledDetector(det, cols=tiling_cols, rows=tiling_rows,
                              conf_threshold=tiling_conf, nms_iou=tiling_nms_iou)
        tiled_boxes = tiled.detect(img)
        n_tiled_raw = len(tiled_boxes)
        blocks = merge_tiled_new_boxes(blocks, tiled_boxes,
                                       coverage_thresh=coverage_thresh,
                                       conf_thresh=conf_threshold)
        per_engine["rtdetr-v2-tiled"] = len(blocks) - per_engine["rtdetr-v2"]
        per_engine["rtdetr-v2-tiled-raw"] = n_tiled_raw

    elapsed = time.time() - t0
    doc = {
        "work_id": work_id,
        "page": page,
        "source_engines": ["rtdetr-v2"] + (["rtdetr-v2-tiled"] if tiling_enabled else []),
        "n_boxes": len(blocks),
        "per_engine_boxes": per_engine,
        "conf_threshold": conf_threshold,
        "tiling_enabled": tiling_enabled,
        "tiling_grid": [tiling_cols, tiling_rows] if tiling_enabled else None,
        "coverage_thresh": coverage_thresh if tiling_enabled else None,
        "elapsed_s": round(elapsed, 2),
        "blocks": blocks,
    }
    target = out_path or (out_dir / f"{page}_detection.json")
    write_json(target, doc)
    return doc


