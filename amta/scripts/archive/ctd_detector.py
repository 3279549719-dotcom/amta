"""CTD (ComicTextDetector) + DB 后处理检测器。

移植自 BallonsTranslator (dmMaze/BallonsTranslator) 的核心推理流程：
- 模型: comictextdetector.pt.onnx (YOLOv5 + UNet + DBNet 三组件)
- 输入: 1024x1024 letterbox
- 输出: YOLO框 + UNet mask + DBNet 线条概率图
- 后处理: SegDetectorRepresenter 从概率图提取四边形框 (比矩形更精确)

关键: DBNet 输出的是文本区域的概率热图，可以提取任意形状的四边形，
这是 CTD 比 RT-DETR-v2 (矩形 bbox) 框得更准的原因。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pyclipper
from shapely.geometry import Polygon


# ---------- 预处理 ----------

def letterbox(img: np.ndarray, new_shape=(1024, 1024), color=(114, 114, 114),
              auto=False, scaleFill=False, scaleup=True, stride=64):
    """缩放并 padding 到 new_shape（与 yolov5 letterbox 一致）。"""
    shape = img.shape[:2]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    if not scaleup:
        r = min(r, 1.0)

    ratio = r, r
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]

    if auto:
        dw, dh = np.mod(dw, stride), np.mod(dh, stride)
    elif scaleFill:
        dw, dh = 0.0, 0.0
        new_unpad = (new_shape[1], new_shape[0])
        ratio = new_shape[1] / shape[1], new_shape[0] / shape[0]

    dw /= 2
    dh /= 2

    if shape[::-1] != new_unpad:
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return img, ratio, (dw, dh)


# ---------- DB 后处理 (移植自 db_utils.py SegDetectorRepresenter) ----------

class SegDetectorRepresenter:
    """从 DBNet 概率图提取四边形框。"""

    def __init__(self, thresh=0.3, box_thresh=0.7, max_candidates=1000, unclip_ratio=1.5):
        self.min_size = 3
        self.thresh = thresh
        self.box_thresh = box_thresh
        self.max_candidates = max_candidates
        self.unclip_ratio = unclip_ratio

    def __call__(self, pred, height=None, width=None):
        """pred: [1, 2, H, W] (shrink_map + threshold_map)，返回 (boxes_batch, scores_batch)。"""
        pred = pred[:, 0, :, :]  # 取 shrink_map
        segmentation = pred > self.thresh

        batch_size = pred.shape[0]
        if height is None:
            height = pred.shape[1]
        if width is None:
            width = pred.shape[2]

        boxes_batch = []
        scores_batch = []
        for b in range(batch_size):
            boxes, scores = self.boxes_from_bitmap(pred[b], segmentation[b], width, height)
            boxes_batch.append(boxes)
            scores_batch.append(scores)
        return boxes_batch, scores_batch

    def boxes_from_bitmap(self, pred, bitmap, dest_width, dest_height):
        bitmap = bitmap.astype(np.uint8)
        contours, _ = cv2.findContours(bitmap, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        num_contours = min(len(contours), self.max_candidates)
        boxes = np.zeros((num_contours, 4, 2), dtype=np.int64)
        scores = np.zeros((num_contours,), dtype=np.float32)

        for index in range(num_contours):
            contour = contours[index].squeeze(1)
            points, sside = self.get_mini_boxes(contour)
            if sside < 2:
                continue
            points = np.array(points)
            score = self.box_score_fast(pred, contour)

            box = self.unclip(points, unclip_ratio=self.unclip_ratio).reshape(-1, 1, 2)
            box, sside = self.get_mini_boxes(box)
            box = np.array(box)

            box[:, 0] = np.clip(np.round(box[:, 0] / bitmap.shape[1] * dest_width), 0, dest_width)
            box[:, 1] = np.clip(np.round(box[:, 1] / bitmap.shape[0] * dest_height), 0, dest_height)
            boxes[index, :, :] = box.astype(np.int64)
            scores[index] = score
        return boxes, scores

    def unclip(self, box, unclip_ratio=1.5):
        poly = Polygon(box)
        distance = poly.area * unclip_ratio / poly.length
        offset = pyclipper.PyclipperOffset()
        offset.AddPath(box, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
        expanded = np.array(offset.Execute(distance))
        return expanded

    def get_mini_boxes(self, contour):
        bounding_box = cv2.minAreaRect(contour)
        points = sorted(list(cv2.boxPoints(bounding_box)), key=lambda x: x[0])
        index_1, index_2, index_3, index_4 = 0, 1, 2, 3
        if points[1][1] > points[0][1]:
            index_1, index_4 = 0, 1
        else:
            index_1, index_4 = 1, 0
        if points[3][1] > points[2][1]:
            index_2, index_3 = 2, 3
        else:
            index_2, index_3 = 3, 2
        box = [points[index_1], points[index_2], points[index_3], points[index_4]]
        return box, min(bounding_box[1])

    def box_score_fast(self, bitmap, _box):
        h, w = bitmap.shape[:2]
        box = _box.copy()
        xmin = np.clip(np.floor(box[:, 0].min()).astype(np.int64), 0, w - 1)
        xmax = np.clip(np.ceil(box[:, 0].max()).astype(np.int64), 0, w - 1)
        ymin = np.clip(np.floor(box[:, 1].min()).astype(np.int64), 0, h - 1)
        ymax = np.clip(np.ceil(box[:, 1].max()).astype(np.int64), 0, h - 1)
        mask = np.zeros((ymax - ymin + 1, xmax - xmin + 1), dtype=np.uint8)
        box[:, 0] = box[:, 0] - xmin
        box[:, 1] = box[:, 1] - ymin
        cv2.fillPoly(mask, box.reshape(1, -1, 2).astype(np.int32), 1)
        return cv2.mean(bitmap[ymin:ymax + 1, xmin:xmax + 1], mask)[0]


# ---------- 工具函数 ----------

def quad_to_bbox(quad: np.ndarray) -> list[float]:
    """四边形 [4,2] 转外接矩形 [x1,y1,x2,y2]。"""
    return [float(quad[:, 0].min()), float(quad[:, 1].min()),
            float(quad[:, 0].max()), float(quad[:, 1].max())]


def seg_rep_extract_boxes(prob_map: np.ndarray, orig_h: int, orig_w: int,
                          box_thresh: float = 0.6) -> list[list[float]]:
    """从单通道概率图提取框（纯函数，供测试用）。"""
    seg = SegDetectorRepresenter(thresh=0.3, box_thresh=box_thresh)
    pred = prob_map[np.newaxis, np.newaxis, :, :]  # [1,1,H,W]
    # 构造假的 2 通道输入 (shrink + threshold)
    pred_2ch = np.concatenate([pred, pred], axis=1)
    boxes, scores = seg(pred_2ch, height=orig_h, width=orig_w)
    idx = np.where(scores[0] > box_thresh)
    quads = boxes[0][idx]
    return [quad_to_bbox(q) for q in quads]


# ---------- 检测器 ----------

class CtdDetector:
    """CTD + DB 后处理检测器。

    输出四边形框（精确），同时提供外接矩形（兼容 OCR crop）。
    """
    name = "ctd-db"

    def __init__(self, model_path: str | Path | None = None, input_size: int = 1024,
                 conf_thresh: float = 0.4, box_thresh: float = 0.6,
                 nms_thresh: float = 0.35):
        if model_path is None:
            model_path = Path(__file__).resolve().parent.parent / "models" / "CTD" / "comictextdetector.pt.onnx"
        self.model_path = Path(model_path)
        self.input_size = input_size
        self.conf_thresh = conf_thresh
        self.box_thresh = box_thresh
        self.nms_thresh = nms_thresh
        self.seg_rep = SegDetectorRepresenter(thresh=0.3)
        self._net = None
        self._load()

    def _load(self):
        if not self.model_path.exists():
            raise FileNotFoundError(f"CTD model not found: {self.model_path}")
        self._net = cv2.dnn.readNetFromONNX(str(self.model_path))
        self._net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self._net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self._out_names = self._net.getUnconnectedOutLayersNames()

    def detect(self, img_bgr: np.ndarray) -> tuple[list[dict], float]:
        """检测，返回 (blocks, elapsed_sec)。

        blocks: [{"bbox": [x1,y1,x2,y2], "quad": [[x,y]x4], "source": "ctd-db", "score": float}]
        """
        import time
        t0 = time.perf_counter()

        im_h, im_w = img_bgr.shape[:2]

        # 1. letterbox 预处理
        img_in, ratio, (dw, dh) = letterbox(img_bgr, new_shape=(self.input_size, self.input_size),
                                            auto=False, stride=64)

        # 2. 推理
        blob = cv2.dnn.blobFromImage(img_in, scalefactor=1.0 / 255.0,
                                     size=(self.input_size, self.input_size), swapRB=False)
        self._net.setInput(blob)
        outputs = self._net.forward(self._out_names)

        # 3. 解析输出 (blks, mask, lines_map)
        # 有些 OpenCV 版本会反转 mask 和 lines_map 的顺序
        blks, mask, lines_map = outputs[0], outputs[1], outputs[2]
        if mask.ndim == 4 and mask.shape[1] == 2:
            # mask 实际上是 lines_map (2通道)，反转
            mask, lines_map = lines_map, mask

        # 4. 裁剪 padding 区域
        dh_int = int(round(dh))
        dw_int = int(round(dw))
        if mask.ndim == 4:
            mask = mask[0, 0]
        mask = mask[:mask.shape[0] - dh_int * 2, :mask.shape[1] - dw_int * 2]
        lines_map = lines_map[:, :, :lines_map.shape[2] - dh_int * 2, :lines_map.shape[3] - dw_int * 2]

        # 5. DB 后处理提取四边形
        boxes, scores = self.seg_rep(lines_map, height=im_h, width=im_w)
        idx = np.where(scores[0] > self.box_thresh)
        quads = boxes[0][idx]
        quad_scores = scores[0][idx]

        # 6. 四边形转外接矩形 + 过滤
        blocks = []
        for i, (quad, score) in enumerate(zip(quads, quad_scores)):
            bbox = quad_to_bbox(quad)
            x1, y1, x2, y2 = bbox
            if x2 - x1 < 3 or y2 - y1 < 3:
                continue
            blocks.append({
                "bbox": bbox,
                "quad": quad.tolist(),
                "source": self.name,
                "score": float(score),
                "region_id": f"r{i:02d}",
            })

        elapsed = time.perf_counter() - t0
        return blocks, elapsed
