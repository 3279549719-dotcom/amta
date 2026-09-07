"""最终落地账目：主链(整图0.7) ∪ 瓦片化新增(≥0.7)。

架构：主链保留整图640 conf0.7 的框；瓦片化(2×3+3×4双网格)产出新框，
只收"与主链不重叠"且 conf≥0.7 的新增框。碎片自动归主链。
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
PAGES = [14, 15, 17, 19]
KNOWN = {
    14: [("いたい!", [614, 1498, 654, 1621])],
    15: [("はい", [1394, 770, 1460, 889])],
    17: [("おとな…", [427, 2294, 489, 2449]), ("ご苦労", [1323, 522, 1388, 664])],
    19: [("そぉ～", [110, 311, 314, 408]), ("サグ姉", [799, 2454, 851, 2553])],
}


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


def tiled_new_ge07(img, whole):
    """瓦片化(2x3+3x4)新增框：与主链不重叠 + conf>=0.7。"""
    all_d = []
    for c, r in [(2, 3), (3, 4)]:
        d_ = raw_dets(img, c, r)
        if d_.size:
            all_d.append(d_)
    comb = np.vstack(all_d) if all_d else np.array([]).reshape(0, 6)
    tiled = nms_max_conf(comb, iou_thresh=0.5)
    # 只看 >=0.7
    tiled = [b for b in tiled if b["conf"] >= 0.7]
    # 与主链不重叠
    new = [b for b in tiled if not any(_iou(b["bbox"], w["bbox"]) >= 0.3 for w in whole)]
    return new


def main():
    print(f"{'page':>4} | {'主链':>4} | {'瓦片新增(≥0.7,不重叠)':>18} | {'合并后':>6} | 已知漏检全部≥0.7?")
    for page in PAGES:
        img = cv2.imdecode(np.fromfile(str(RAW / f"{page}.jpg"), dtype=np.uint8), cv2.IMREAD_COLOR)
        whole = whole_ge07(img)
        new = tiled_new_ge07(img, whole)
        known = KNOWN[page]
        # 检查已知漏检在合并集中是否都有 conf>=0.7 的框
        merged = whole + new
        checks = []
        for name, kb in known:
            best = max(merged, key=lambda b: _iou(b["bbox"], kb)) if merged else None
            iou = _iou(best["bbox"], kb) if best else 0
            ok = best and iou >= 0.3 and best["conf"] >= 0.7
            detail = f"{best['conf']:.2f}" if best else "-"
            checks.append(f"{name}:{'✓' if ok else '✗(' + detail + ')'}")
        print(f"{page:>4} | {len(whole):>4} | {len(new):>18} | {len(whole)+len(new):>6} | {'  '.join(checks)}")
        for b in sorted(new, key=lambda x: -x["conf"]):
            print(f"    新增: conf={b['conf']:.3f} bbox={b['bbox']}")


if __name__ == "__main__":
    main()
