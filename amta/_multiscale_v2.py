"""多尺度瓦片化融合 v2：各网格原始框收集 → 按最高 conf 保留代表框（不 merge bbox）。

这是标准的多尺度推理（multi-scale TTA）做法：每个网格独立检测，
同位置重复检测时保留最高 conf 的那个框，不破坏原始 bbox。
"""
import sys
sys.path.insert(0, r"E:\manga translator agent\amta\src")
import cv2
import numpy as np
import _tiling_sweep as ts
from _tiling_sweep import _detect_tile, _iou

RAW = r"D:\我的汉化\汉化作品\东方\单翼停留之地"
KNOWN = [
    (14, "いたい!", [614, 1498, 654, 1621]),
    (15, "はい", [1394, 770, 1460, 889]),
    (17, "おとな…", [427, 2294, 489, 2449]),
    (17, "ご苦労", [1323, 522, 1388, 664]),
    (19, "そぉ～", [110, 311, 314, 408]),
]


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


def nms_max_conf(dets: np.ndarray, iou_thresh: float = 0.5) -> list[dict]:
    """按 conf 降序，保留 IoU 高于阈值的最高 conf 框（不合并 bbox）。"""
    if dets.size == 0:
        return []
    order = np.argsort(-dets[:, 5])
    keep = []
    suppressed = set()
    for i in order:
        if i in suppressed:
            continue
        keep.append(dets[i])
        for j in order:
            if j in suppressed or j == i:
                continue
            if _iou([int(v) for v in dets[i][:4]], [int(v) for v in dets[j][:4]]) >= iou_thresh:
                suppressed.add(j)
    return [{"bbox": [int(v) for v in d[:4]], "label": int(d[4]), "conf": float(d[5])} for d in keep]


def main():
    print("=== 多尺度融合 v2: 2x3+3x4, NMS max-conf ===")
    for page in [14, 15, 17, 19]:
        img = cv2.imdecode(np.fromfile(rf"{RAW}\{page}.jpg", dtype="uint8"), cv2.IMREAD_COLOR)
        all_dets = []
        for cols, rows in [(2, 3), (3, 4)]:
            all_dets.append(raw_dets(img, cols, rows))
        combined = np.vstack(all_dets) if all_dets else np.array([]).reshape(0, 6)
        blocks = nms_max_conf(combined)
        known = [(n, b) for p, n, b in KNOWN if p == page]
        cells = []
        for n, kb in known:
            best = max(blocks, key=lambda b: _iou(b["bbox"], kb)) if blocks else None
            iou = _iou(best["bbox"], kb) if best else 0
            cells.append(
                f"{n}: {best['conf']:.3f} iou={iou:.2f}" if best and iou >= 0.3 else f"{n}: MISS"
            )
        print(f"page {page}: {' | '.join(cells)}  (total {len(blocks)} 框)")


if __name__ == "__main__":
    main()
