"""补齐 30 个新增框的真实 bbox（重跑有新增的页），OCR+rule_filter 落盘正确明细。"""
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
CROP_NEW = OUT / "crops_new"

COVERAGE_THRESH = 0.5
CONF_KEEP = 0.7


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


def tiled_34(img):
    d_ = raw_dets(img, 3, 4)
    if not d_.size:
        return []
    return nms_max_conf(d_, iou_thresh=0.5)


def coverage_of(c, main_boxes):
    ac = _area(c)
    if ac <= 0:
        return 0.0
    return max((_inter(c, m["bbox"]) / ac for m in main_boxes), default=0.0)


def main():
    # 目标：crops_new 的 conf 集合
    crops = sorted(CROP_NEW.glob("*.png"))
    want = {}  # page -> [(conf, crop)]
    for p in crops:
        page = int(p.name.split("_")[0][1:])
        conf = float(p.name.split("c")[1][:-4])
        want.setdefault(page, []).append((conf, p.name))

    # 逐页重跑，找回 bbox（按 conf 匹配）
    new_blocks = []
    for page in sorted(want):
        img = cv2.imdecode(np.fromfile(str(RAW / f"{page}.jpg"), dtype=np.uint8), cv2.IMREAD_COLOR)
        whole = whole_ge07(img)
        tiled = tiled_34(img)
        candidates = [b for b in tiled
                      if b["conf"] >= CONF_KEEP and coverage_of(b["bbox"], whole) < COVERAGE_THRESH]
        for conf, crop in want[page]:
            hit = min(candidates, key=lambda c: abs(c["conf"] - conf), default=None)
            if hit is None:
                print(f"!! p{page} conf={conf:.3f} 未匹配到 bbox（{crop}）")
                new_blocks.append({"page": page, "conf": conf, "crop": crop, "bbox": None})
            else:
                new_blocks.append({"page": page, "conf": conf, "crop": crop, "bbox": hit["bbox"]})
                candidates.remove(hit)

    # OCR（hayai）
    from amta.ocr_engines import ocr_batch
    from amta.rule_filter import rule_filter

    print(f"[OCR] {len(new_blocks)} 框识别中...")
    ocr_rows = ocr_batch([str(CROP_NEW / b["crop"]) for b in new_blocks], engine="hayai")
    ocr_by_crop = {Path(r["crop"]).name: (r.get("ocr") or "").strip() for r in ocr_rows}
    for b in new_blocks:
        b["text"] = ocr_by_crop.get(b["crop"], "")

    kept, removed = rule_filter(new_blocks, 2243, 3465)
    for b in kept:
        b["verdict"] = "keep"
    for b in removed:
        b["verdict"] = "drop"

    (OUT / "new_blocks_detail.json").write_text(
        json.dumps(new_blocks, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n=== 正确逐框明细（keep={len(kept)} / drop={len(removed)}）===")
    for b in sorted(new_blocks, key=lambda x: (x["page"], -x["conf"])):
        bb = b.get("bbox")
        bb_s = f"[{bb[0]},{bb[1]},{bb[2]},{bb[3]}]" if bb else "NO-BBOX"
        print(f"p{b['page']:>2} conf={b['conf']:.3f} [{b['verdict']:<4}] {bb_s}  {b['text'][:26]!r}")


if __name__ == "__main__":
    main()
