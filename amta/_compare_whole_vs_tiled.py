"""精确对比：整图640 vs 瓦片融合，在各 conf 档位的框数 + 新增框裁剪。

回答用户问题：
1. 瓦片化相对整图640，conf>=0.7 多了哪些框？多的是真字还是杂质？
2. 黄框(0.3~0.7)里杂质占比多少？
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"E:\manga translator agent\amta\src")

import cv2
import numpy as np
from PIL import Image

from _multiscale_v2 import raw_dets, nms_max_conf
import _tiling_sweep as ts

RAW = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT = Path(r"E:\manga translator agent\amta\_tiling_audit\new_by_tiling")
OUT.mkdir(exist_ok=True)

PAGES = [14, 15, 17, 19]


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def whole_blocks(img, conf_thr):
    dets = ts._detect_tile(img)  # noqa: SLF001
    dets = dets[dets[:, 5] >= conf_thr]
    if dets.size == 0:
        return []
    return [{"bbox": [int(v) for v in d[:4]], "conf": float(d[5])} for d in dets]


def fusion_blocks(img):
    all_d = []
    for c, r in [(2, 3), (3, 4)]:
        d_ = raw_dets(img, c, r)
        if d_.size:
            all_d.append(d_)
    comb = np.vstack(all_d) if all_d else np.array([]).reshape(0, 6)
    return nms_max_conf(comb, iou_thresh=0.5)


def main():
    print(f"{'page':>4} | {'whole>=0.7':>10} | {'tiled>=0.7':>10} | {'tiled新增(相对whole>=0.7)':>24} | {'tiled全部0.3~0.7':>16}")
    for page in PAGES:
        img = cv2.imdecode(np.fromfile(str(RAW / f"{page}.jpg"), dtype=np.uint8), cv2.IMREAD_COLOR)
        whole = whole_blocks(img, 0.7)
        fusion = fusion_blocks(img)
        fusion_ge07 = [b for b in fusion if b["conf"] >= 0.7]
        # tiled>=0.7 里，与 whole>=0.7 无重叠的（iou<0.3）算"瓦片化新捞出"
        new = []
        for b in fusion_ge07:
            overlap = any(_iou(b["bbox"], w["bbox"]) >= 0.3 for w in whole)
            if not overlap:
                new.append(b)
        yellows = [b for b in fusion if b["conf"] < 0.7]
        print(f"{page:>4} | {len(whole):>10} | {len(fusion_ge07):>10} | {len(new):>24} | {len(yellows):>16}")
        # 裁剪新捞出的绿框
        for b in sorted(new, key=lambda x: -x["conf"]):
            bb = [int(v) for v in b["bbox"]]
            pad = 8
            x1, y1 = max(0, bb[0] - pad), max(0, bb[1] - pad)
            x2, y2 = min(img.shape[1], bb[2] + pad), min(img.shape[0], bb[3] + pad)
            crop = img[y1:y2, x1:x2]
            scale = 400 / max(crop.shape[:2])
            crop = cv2.resize(crop, (int(crop.shape[1] * scale), int(crop.shape[0] * scale)),
                              interpolation=cv2.INTER_LANCZOS4)
            fname = OUT / f"p{page}_NEWGREEN_{b['conf']:.3f}_{x1}_{y1}.png"
            cv2.imencode(".png", crop)[1].tofile(str(fname))
            print(f"    NEW>=0.7: conf={b['conf']:.3f} bbox={bb} -> {fname.name}")


if __name__ == "__main__":
    main()
