"""dump coverage 中间地带框（0.3~0.9）身份，验证骑墙框假设。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, r"E:\manga translator agent\amta\src")

import cv2
import numpy as np

import _tiling_sweep as ts
from _multiscale_v2 import raw_dets, nms_max_conf

RAW = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT = Path(r"E:\manga translator agent\amta\output\tiling_full42")


def _area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _inter(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy


def whole_ge07(img):
    dets = ts._detect_tile(img)
    dets = dets[dets[:, 5] >= 0.7]
    if dets.size == 0:
        return []
    return [{"bbox": [int(v) for v in d[:4]], "conf": float(d[5])} for d in dets]


def coverage_of(c, main_boxes):
    ac = _area(c)
    if ac <= 0:
        return 0.0
    return max((_inter(c, m["bbox"]) / ac for m in main_boxes), default=0.0)


def main():
    mid = []
    for page in range(42):
        img = cv2.imdecode(np.fromfile(str(RAW / f"{page}.jpg"), dtype=np.uint8), cv2.IMREAD_COLOR)
        whole = whole_ge07(img)
        d_ = raw_dets(img, 3, 4)
        if d_.size:
            d_ = nms_max_conf(d_, iou_thresh=0.5)
        else:
            d_ = []
        for b in d_:
            if b["conf"] < 0.3:
                continue
            cov = coverage_of(b["bbox"], whole)
            if 0.3 <= cov < 0.9:
                mid.append({"page": page, "conf": b["conf"], "bbox": b["bbox"], "coverage": round(cov, 3)})
        if page % 10 == 0:
            print(f"page {page} done, mid={len(mid)}")

    (OUT / "coverage_mid_zone.json").write_text(json.dumps(mid, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== 中间地带框（0.3<=cov<0.9）共 {len(mid)} 个 ===")
    for m in sorted(mid, key=lambda x: x["coverage"]):
        print(f"p{m['page']:>2} conf={m['conf']:.3f} cov={m['coverage']:.3f} bbox={m['bbox']}")


if __name__ == "__main__":
    main()
