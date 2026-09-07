"""全 42 页瓦片化副引擎全量分析。

流程：主链(整图640 conf0.7) + 瓦片化融合(2x3+3x4, conf>=0.3, NMS max-conf)
     → coverage(主链覆盖 C 比例)>=0.5 判碎片丢弃
     → 新增框(conf>=0.7 且非碎片) 裁剪 → OCR(hayai) → rule_filter
     → 统计：新增真字 / 剩余杂质 / 各档 coverage 分布

输出：JSON 账目 + 裁剪图（新增框、杂质框）
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"E:\manga translator agent\amta\src")

import cv2
import numpy as np

import _tiling_sweep as ts
from _multiscale_v2 import raw_dets, nms_max_conf

RAW = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT = Path(r"E:\manga translator agent\amta\output\tiling_full42")
OUT.mkdir(exist_ok=True)
CROP_NEW = OUT / "crops_new"
CROP_IMPURITY = OUT / "crops_impurity"
CROP_NEW.mkdir(exist_ok=True)
CROP_IMPURITY.mkdir(exist_ok=True)

PAGES = list(range(0, 42))  # 0~41
COVERAGE_THRESH = 0.5
CONF_KEEP = 0.7


def _area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _inter(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy


def _iou(a, b):
    ia = _inter(a, b)
    ua = _area(a) + _area(b) - ia
    return ia / ua if ua > 0 else 0.0


def whole_ge07(img):
    dets = ts._detect_tile(img)  # noqa: SLF001
    dets = dets[dets[:, 5] >= 0.7]
    if dets.size == 0:
        return []
    return [{"bbox": [int(v) for v in d[:4]], "conf": float(d[5])} for d in dets]


def tiled_fusion(img):
    """纯 3×4 网格（用户定案）。"""
    d_ = raw_dets(img, 3, 4)
    if not d_.size:
        return np.array([]).reshape(0, 6)
    return nms_max_conf(d_, iou_thresh=0.5)


def coverage_of(c, main_boxes):
    """C 被主链任一框覆盖的最大比例。"""
    ac = _area(c)
    if ac <= 0:
        return 0.0
    return max((_inter(c, m["bbox"]) / ac for m in main_boxes), default=0.0)


def main():
    # 读取 ocr 引擎（懒加载，hayai）
    from amta.ocr_engines import ocr_batch
    from amta.rule_filter import rule_filter
    from PIL import Image

    ledger = []
    all_new = []       # 新增框汇总（含 OCR 结果）
    coverage_bins = {"0-0.1": 0, "0.1-0.3": 0, "0.3-0.5": 0,
                     "0.5-0.7": 0, "0.7-0.9": 0, "0.9-1.0": 0}

    t0 = time.time()
    for page in PAGES:
        img_path = RAW / f"{page}.jpg"
        img = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        whole = whole_ge07(img)
        tiled = tiled_fusion(img)

        # coverage 分布（所有 conf>=0.3 瓦片框）
        for b in tiled:
            if b["conf"] < 0.3:
                continue
            cov = coverage_of(b["bbox"], whole)
            if cov < 0.1:
                coverage_bins["0-0.1"] += 1
            elif cov < 0.3:
                coverage_bins["0.1-0.3"] += 1
            elif cov < 0.5:
                coverage_bins["0.3-0.5"] += 1
            elif cov < 0.7:
                coverage_bins["0.5-0.7"] += 1
            elif cov < 0.9:
                coverage_bins["0.7-0.9"] += 1
            else:
                coverage_bins["0.9-1.0"] += 1

        # 新增框：conf>=0.7 且 coverage<0.5
        new_blocks = []
        for b in tiled:
            if b["conf"] < CONF_KEEP:
                continue
            if coverage_of(b["bbox"], whole) >= COVERAGE_THRESH:
                continue
            new_blocks.append(b)

        ledger.append({
            "page": page,
            "n_main": len(whole),
            "n_tiled": len(tiled),
            "n_new": len(new_blocks),
        })
        for b in new_blocks:
            all_new.append({"page": page, **b})
        print(f"page {page:>2}: main={len(whole):>2} tiled={len(tiled):>2} new={len(new_blocks):>2}")

    # ---- OCR + rule_filter 新增框 ----
    print(f"\n[OCR] 新增框共 {len(all_new)} 个，开始 hayai 识别...")
    crops = []
    for i, nb in enumerate(all_new):
        bb = nb["bbox"]
        pad = 6
        img = Image.open(RAW / f"{nb['page']}.jpg")
        x1, y1 = max(0, bb[0] - pad), max(0, bb[1] - pad)
        x2, y2 = min(img.width, bb[2] + pad), min(img.height, bb[3] + pad)
        c = img.crop((x1, y1, x2, y2))
        p = CROP_NEW / f"p{nb['page']}_r{i:03d}_c{nb['conf']:.3f}.png"
        c.save(p)
        crops.append(str(p))

    ocr_rows = ocr_batch(crops, engine="hayai")
    ocr_by_crop = {r["crop"]: (r.get("ocr") or "").strip() for r in ocr_rows}

    # 组装 blocks 供 rule_filter
    for i, nb in enumerate(all_new):
        nb["text"] = ocr_by_crop.get(crops[i], "")

    img_w, img_h = 2243, 3465
    kept_new, removed_new = rule_filter(all_new, img_w, img_h)

    # 分类统计
    n_text = len(kept_new)
    n_impurity = len(removed_new)
    reasons = {}
    for b in removed_new:
        reasons[b.get("filter_reason", "?")] = reasons.get(b.get("filter_reason", "?"), 0) + 1

    # 杂质裁剪
    for b in removed_new:
        bb = b["bbox"]
        pad = 6
        img = Image.open(RAW / f"{b['page']}.jpg")
        x1, y1 = max(0, bb[0] - pad), max(0, bb[1] - pad)
        x2, y2 = min(img.width, bb[2] + pad), min(img.height, bb[3] + pad)
        c = img.crop((x1, y1, x2, y2))
        c.save(CROP_IMPURITY / f"p{b['page']}_c{b['conf']:.3f}_t{b.get('filter_reason','?')}.png")

    elapsed = time.time() - t0

    summary = {
        "pages": len(PAGES),
        "elapsed_s": round(elapsed, 1),
        "total_main": sum(l["n_main"] for l in ledger),
        "total_tiled": sum(l["n_tiled"] for l in ledger),
        "total_new": len(all_new),
        "after_rule_filter_kept": n_text,
        "after_rule_filter_removed": n_impurity,
        "rule_reasons": reasons,
        "coverage_bins": coverage_bins,
        "page_ledger": ledger,
    }
    out_json = OUT / "summary.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n===== 汇总 =====")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("page_ledger",)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
