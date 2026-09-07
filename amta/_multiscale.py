"""多尺度瓦片化融合：2x3 ∪ 3x4，NMS 合并，取最高 conf。

预期：いたい! 从 3x4 拿 0.771，ご苦労 从 2x3 拿 0.872，其余取两档最高。
"""
import sys
sys.path.insert(0, r"E:\manga translator agent\amta\src")
import cv2
import numpy as np
import _tiling_sweep as ts
from _tiling_sweep import detect_tiled, KNOWN, _iou, _detect_tile, _merge_boxes

RAW = r"D:\我的汉化\汉化作品\东方\单翼停留之地"


def detect_multiscale(img, grids=((2, 3), (3, 4))):
    """多网格检测，合并所有框，NMS。"""
    all_dets = []
    for cols, rows in grids:
        ts.TILE_COLS, ts.TILE_ROWS = cols, rows
        # 复用 detect_tiled 但需要拿到原始检测框（conf>=0.3），再合并
        h, w = img.shape[:2]
        tile_w = w / cols
        tile_h = h / rows
        step_w = tile_w * (1 - ts.OVERLAP)
        step_h = tile_h * (1 - ts.OVERLAP)
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
                all_dets.append(dets)
    combined = np.vstack(all_dets) if all_dets else np.array([]).reshape(0, 6)
    combined = _merge_boxes(combined)
    return [{"bbox": [int(v) for v in d[:4]], "label": int(d[4]), "conf": float(d[5])} for d in combined]


def main():
    print("=== 多尺度融合 2x3+3x4 ===")
    for page in [14, 15, 17, 19]:
        img = cv2.imdecode(
            np.fromfile(rf"{RAW}\{page}.jpg", dtype="uint8"), cv2.IMREAD_COLOR
        )
        blocks = detect_multiscale(img)
        known = [(n, b) for p, n, b in KNOWN if p == page]
        cells = []
        for n, kb in known:
            best = max(blocks, key=lambda b: _iou(b["bbox"], kb)) if blocks else None
            iou = _iou(best["bbox"], kb) if best else 0
            cells.append(
                f"{n}: {best['conf']:.3f} iou={iou:.2f}" if best and iou >= 0.3 else f"{n}: MISS"
            )
        print(f"page {page}: {' | '.join(cells)}  (total {len(blocks)} 框)")

    # 额外：p19 看「サグ姉」是否也被捞到
    img = cv2.imdecode(np.fromfile(rf"{RAW}\19.jpg", dtype="uint8"), cv2.IMREAD_COLOR)
    blocks = detect_multiscale(img)
    for b in blocks:
        if abs(b["bbox"][0] - 799) < 30 and abs(b["bbox"][1] - 2454) < 30:
            print("p19 サグ姉:", b)


if __name__ == "__main__":
    main()
