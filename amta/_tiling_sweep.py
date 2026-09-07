"""瓦片化检测实验：p14/15/17/19 × 2×3 网格切块。

核心假设：模型被训练在 640 尺度，直接提高输入分辨率会尺度失配；
改为保持 640 输入，但把原图切成小瓦片，每块单独检测，再映射回原图坐标。
这样小字在模型眼里从 ~11px 放大到 ~33px，而模型仍工作在熟悉的尺度。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, r"E:\manga translator agent\amta\src")

import cv2
import numpy as np
import onnxruntime as ort

from amta.detect_station import merge_duplicate_boxes, remove_contained_boxes

MODEL = Path(r"E:\manga translator agent\amta\models\CTBD\detector.onnx")
RAW = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
PAGES = [14, 15, 17, 19]
CONF = 0.3
TILE_COLS, TILE_ROWS = 2, 3  # 2×3 网格 → 每块 ~1121×1155
OVERLAP = 0.15  # 15% 重叠，避免跨块文字被切断

# 已知漏检小字（原图坐标）
KNOWN = [
    (14, "いたい!", [614, 1498, 654, 1621]),
    (15, "はい", [1394, 770, 1460, 889]),
    (17, "おとな…", [427, 2294, 489, 2449]),
    (17, "ご苦労", [1323, 522, 1388, 664]),
    (19, "そぉ～", [110, 311, 314, 408]),
]

_session = None


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _detect_tile(img: np.ndarray, res: int = 640) -> np.ndarray:
    """单瓦片检测，返回 [x1,y1,x2,y2,label,conf]（瓦片内坐标）。"""
    global _session
    if _session is None:
        _session = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    h_orig, w_orig = img.shape[:2]
    resized = cv2.resize(img, (res, res), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    chw = rgb.transpose(2, 0, 1).astype(np.float32) / 255.0
    input_tensor = np.expand_dims(chw, axis=0)
    orig_sizes = np.array([[w_orig, h_orig]], dtype=np.int64)
    outputs = _session.run(None, {
        "images": input_tensor,
        "orig_target_sizes": orig_sizes,
    })
    labels, boxes, scores = outputs[0], outputs[1], outputs[2]
    dets = []
    for box, score, label in zip(boxes[0], scores[0], labels[0]):
        if score < CONF:
            continue
        if label in (1, 2):
            x1, y1, x2, y2 = map(int, box)
            dets.append([x1, y1, x2, y2, int(label), float(score)])
    return np.array(dets) if dets else np.array([]).reshape(0, 6)


def _merge_boxes(boxes: np.ndarray) -> np.ndarray:
    if boxes.size > 0:
        boxes = merge_duplicate_boxes(boxes, iou_thresh=0.7)
        boxes = remove_contained_boxes(boxes, threshold=0.8)
    return boxes


def detect_whole(img: np.ndarray) -> list[dict]:
    """整图 640 基线。"""
    dets = _detect_tile(img)
    dets = _merge_boxes(dets)
    return [{"bbox": [int(v) for v in d[:4]], "label": int(d[4]), "conf": float(d[5])} for d in dets]


def detect_tiled(img: np.ndarray) -> list[dict]:
    """2×3 网格瓦片化检测，坐标映射回原图。"""
    h, w = img.shape[:2]
    tile_w = w / TILE_COLS
    tile_h = h / TILE_ROWS
    step_w = tile_w * (1 - OVERLAP)
    step_h = tile_h * (1 - OVERLAP)
    all_dets = []
    for r in range(TILE_ROWS):
        for c in range(TILE_COLS):
            x0 = max(0, int(c * step_w))
            y0 = max(0, int(r * step_h))
            x1 = min(w, int(x0 + tile_w))
            y1 = min(h, int(y0 + tile_h))
            tile = img[y0:y1, x0:x1].copy()
            dets = _detect_tile(tile)
            if dets.size == 0:
                continue
            # 映射回原图坐标
            dets = dets.copy()
            dets[:, [0, 2]] += x0
            dets[:, [1, 3]] += y0
            all_dets.append(dets)
    combined = np.vstack(all_dets) if all_dets else np.array([]).reshape(0, 6)
    combined = _merge_boxes(combined)
    return [{"bbox": [int(v) for v in d[:4]], "label": int(d[4]), "conf": float(d[5])} for d in combined]


def main():
    for page in PAGES:
        img = cv2.imdecode(np.fromfile(str(RAW / f"{page}.jpg"), dtype=np.uint8), cv2.IMREAD_COLOR)
        known = [(n, b) for p, n, b in KNOWN if p == page]
        print(f"\n{'='*72}\nPAGE {page}  (known: {[n for n, _ in known]})\n{'='*72}")

        for name, blocks in [("whole640", detect_whole(img)), ("tiled2x3", detect_tiled(img))]:
            cells = []
            for n, kb in known:
                if blocks:
                    best = max(blocks, key=lambda b: _iou(b["bbox"], kb))
                    iou = _iou(best["bbox"], kb)
                else:
                    best, iou = None, 0.0
                if best and iou >= 0.3:
                    cells.append(f"{best['conf']:.3f}")
                else:
                    cells.append("  -- ")
            print(f"{name:>9} | {len(blocks):>3} 框 | " + " | ".join(cells))

        # 瓦片化的全部框明细（conf 排序）
        tiled = detect_tiled(img)
        print(f"  -- tiled 全部框明细（conf>=0.3，{len(tiled)} 个）：")
        for b in sorted(tiled, key=lambda x: -x["conf"])[:18]:
            bb = b["bbox"]
            print(f"     conf={b['conf']:.3f} bbox={bb} label={b['label']}")


if __name__ == "__main__":
    main()
