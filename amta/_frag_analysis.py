"""3×4 单网格 vs 整图0.7：完整框账 + 机械去重效果演示。

回答用户：
1. 瓦片化3×4 相对整图0.7，框暴增多少？其中多少是"碎片/重复"（可机械合并）？
2. 应用"与主链重叠合并 + NMS"后，最终净增多少框？净增里真/假比例？
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"E:\manga translator agent\amta\src")

import cv2
import numpy as np

import _tiling_sweep as ts
from _multiscale_v2 import raw_dets, nms_max_conf

RAW = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT = Path(r"E:\manga translator agent\amta\_tiling_audit\frag")
OUT.mkdir(exist_ok=True)

PAGES = [14, 15, 17, 19]


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def whole_ge07(img):
    dets = ts._detect_tile(img)  # noqa: SLF001
    dets = dets[dets[:, 5] >= 0.7]
    if dets.size == 0:
        return []
    return [{"bbox": [int(v) for v in d[:4]], "conf": float(d[5])} for d in dets]


def tiled34_ge03(img):
    dets = raw_dets(img, 3, 4)
    dets = dets[dets[:, 5] >= 0.3]
    if dets.size == 0:
        return []
    return [{"bbox": [int(v) for v in d[:4]], "conf": float(d[5])} for d in dets]


def classify(blocks, whole):
    """把瓦片框分类：碎片(与整图框IoU>=0.3) / 新增(不重叠)。"""
    frag, new = [], []
    for b in blocks:
        overlap = any(_iou(b["bbox"], w["bbox"]) >= 0.3 for w in whole)
        (frag if overlap else new).append(b)
    return frag, new


def main():
    print(f"{'page':>4} | {'整图0.7':>7} | {'瓦片3x4全(>=0.3)':>14} | {'其中碎片':>6} | {'新增(不重叠)':>10} | {'新增≥0.7':>8}")
    for page in PAGES:
        img = cv2.imdecode(np.fromfile(str(RAW / f"{page}.jpg"), dtype=np.uint8), cv2.IMREAD_COLOR)
        whole = whole_ge07(img)
        tiled = tiled34_ge03(img)
        frag, new = classify(tiled, whole)
        new_ge07 = [b for b in new if b["conf"] >= 0.7]
        print(f"{page:>4} | {len(whole):>7} | {len(tiled):>14} | {len(frag):>6} | {len(new):>10} | {len(new_ge07):>8}")
        # 碎片明细：一个整图大框对应几个碎片
        if frag:
            print(f"   碎片 {len(frag)} 个（conf 排序）:")
            for b in sorted(frag, key=lambda x: -x["conf"])[:12]:
                print(f"     conf={b['conf']:.3f} bbox={b['bbox']}")
        if new_ge07:
            print(f"   新增≥0.7 {len(new_ge07)} 个:")
            for b in sorted(new_ge07, key=lambda x: -x["conf"]):
                print(f"     conf={b['conf']:.3f} bbox={b['bbox']}")


if __name__ == "__main__":
    main()
