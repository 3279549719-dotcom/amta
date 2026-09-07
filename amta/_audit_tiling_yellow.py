"""统计并裁剪融合结果里 conf 0.3~0.7（黄框）和 >=0.7（绿框）的框，逐框核对内容。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"E:\manga translator agent\amta\src")

import cv2
import numpy as np
from PIL import Image, ImageDraw

from _multiscale_v2 import raw_dets, nms_max_conf

RAW = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT = Path(r"E:\manga translator agent\amta\_tiling_audit")
OUT.mkdir(exist_ok=True)

PAGES = [14, 15, 17, 19]


def fusion_blocks(img):
    all_d = []
    for c, r in [(2, 3), (3, 4)]:
        d_ = raw_dets(img, c, r)
        if d_.size:
            all_d.append(d_)
    comb = np.vstack(all_d) if all_d else np.array([]).reshape(0, 6)
    return nms_max_conf(comb, iou_thresh=0.5)


def main():
    for page in PAGES:
        img = cv2.imdecode(np.fromfile(str(RAW / f"{page}.jpg"), dtype=np.uint8), cv2.IMREAD_COLOR)
        blocks = fusion_blocks(img)
        greens = [b for b in blocks if b["conf"] >= 0.7]
        yellows = [b for b in blocks if b["conf"] < 0.7]
        print(f"\n=== page {page}: 绿(>=0.7)={len(greens)}  黄(0.3~0.7)={len(yellows)} ===")
        for b in sorted(yellows, key=lambda x: -x["conf"]):
            bb = [int(v) for v in b["bbox"]]
            print(f"  黄 conf={b['conf']:.3f} bbox={bb}")
            # 裁剪放大
            pad = 8
            x1, y1 = max(0, bb[0] - pad), max(0, bb[1] - pad)
            x2, y2 = min(img.shape[1], bb[2] + pad), min(img.shape[0], bb[3] + pad)
            crop = img[y1:y2, x1:x2]
            scale = 400 / max(crop.shape[:2])
            crop = cv2.resize(crop, (int(crop.shape[1] * scale), int(crop.shape[0] * scale)),
                              interpolation=cv2.INTER_LANCZOS4)
            fname = OUT / f"p{page}_yellow_{b['conf']:.3f}_{x1}_{y1}.png"
            cv2.imencode(".png", crop)[1].tofile(str(fname))
            print(f"    -> {fname.name}")


if __name__ == "__main__":
    main()
