"""分辨率扫描实验：p14/15/17/19 × 640/960/1280/1600/1920。

不改源码，参数化 RT-DETR 输入分辨率，对比：
- 每个已知漏检小字的 conf 随分辨率的变化
- 每页总框数（杂质水平）
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
RESOLUTIONS = [640, 960, 1280, 1600, 1920]
CONF = 0.3  # 模型内部默认阈值，保留所有响应看 conf 提升

# 已知漏检小字（原图坐标）: (page, name, bbox)
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


def detect_at_resolution(img: np.ndarray, res: int) -> list[dict]:
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
    dets = np.array(dets) if dets else np.array([]).reshape(0, 6)
    if dets.size > 0:
        dets = merge_duplicate_boxes(dets, iou_thresh=0.7)
        dets = remove_contained_boxes(dets, threshold=0.8)
    return [{"bbox": [int(v) for v in d[:4]], "label": int(d[4]), "conf": float(d[5])} for d in dets]


def main():
    for page in PAGES:
        img = cv2.imdecode(np.fromfile(str(RAW / f"{page}.jpg"), dtype=np.uint8), cv2.IMREAD_COLOR)
        known = [(n, b) for p, n, b in KNOWN if p == page]
        print(f"\n{'='*70}\nPAGE {page}  (known: {[(n, b) for n, b in known]})\n{'='*70}")
        header = f"{'res':>5} | {'n_boxes':>7} | " + " | ".join(f"{n} conf" for n, _ in known)
        print(header)
        for res in RESOLUTIONS:
            t0 = time.perf_counter()
            blocks = detect_at_resolution(img, res)
            dt = time.perf_counter() - t0
            # 找每个 known bbox 的最佳覆盖框
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
            print(f"{res:>5} | {len(blocks):>7} ({dt:.1f}s) | " + " | ".join(cells))
            # 额外：列出 res=1280 时 conf>=0.5 的新框（看杂质）
            if res == 1280:
                new = [b for b in blocks if b["conf"] >= 0.5]
                print(f"       (1280: conf>=0.5 共 {len(new)} 框)")


if __name__ == "__main__":
    main()
