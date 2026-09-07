"""检查 p17 融合后框列表，定位ご苦労丢失原因。"""
import sys
sys.path.insert(0, r"E:\manga translator agent\amta\src")
import cv2
import numpy as np
import _tiling_sweep as ts
from _tiling_sweep import _detect_tile, _merge_boxes, _iou

RAW = r"D:\我的汉化\汉化作品\东方\单翼停留之地"
GOKURO = [1323, 522, 1388, 664]


def raw_dets(img, cols, rows):
    h, w = img.shape[:2]
    tile_w = w / cols
    tile_h = h / rows
    step_w = tile_w * (1 - ts.OVERLAP)
    step_h = tile_h * (1 - ts.OVERLAP)
    out = []
    for r in range(rows):
        for c in range(cols):
            x0 = max(0, int(c * step_w))
            y0 = max(0, int(r * step_h))
            x1 = min(w, int(x0 + tile_w))
            y1 = min(h, int(y0 + tile_h))
            tile = img[y0:y1, x0:x1].copy()
            dets = _detect_tile(tile)
            if dets.size == 0:
                continue
            dets = dets.copy()
            dets[:, [0, 2]] += x0
            dets[:, [1, 3]] += y0
            out.append(dets)
    return np.vstack(out) if out else np.array([]).reshape(0, 6)


img = cv2.imdecode(np.fromfile(rf"{RAW}\17.jpg", dtype="uint8"), cv2.IMREAD_COLOR)

for cols, rows in [(2, 3), (3, 4)]:
    dets = raw_dets(img, cols, rows)
    print(f"\n=== grid {cols}x{rows}: raw {len(dets)} dets ===")
    # 找与ご苦労 iou>0.1 的框
    for d in dets:
        iou = _iou([int(v) for v in d[:4]], GOKURO)
        if iou > 0.1:
            print(f"  raw: bbox={[int(v) for v in d[:4]]} conf={d[5]:.3f} iou={iou:.2f}")
    merged = _merge_boxes(dets)
    print(f"  merged: {len(merged)} boxes")
    for d in merged:
        iou = _iou([int(v) for v in d[:4]], GOKURO)
        if iou > 0.1:
            print(f"  merged: bbox={[int(v) for v in d[:4]]} conf={d[5]:.3f} iou={iou:.2f}")
