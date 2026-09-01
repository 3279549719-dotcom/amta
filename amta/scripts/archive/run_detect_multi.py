"""多检测器对比脚本 — 支持任意 Detector 列表，统一 baberu OCR，输出对比 JSON。

用法:
    python scripts/run_detect_multi.py --pages 11 13 14 17 18 --detectors rtdetr koharu ctd
输出:
    output/data/detect_multi/results.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCRIPT_DIR))

from amta.ocr_engines import ocr_batch  # noqa: E402
from detectors import BaselineDetector, CtdDetector, KoharuSingleDetector, RTDetrDetector  # noqa: E402

RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
BACKUP_DIR = ROOT / "output" / "backup" / "2026-08-27-pre-rerun-11-20"
OUT_DIR = ROOT / "output" / "data" / "detect_multi"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CROP_DIR = OUT_DIR / "crops"
CROP_DIR.mkdir(exist_ok=True)


def build_detectors(names: list[str], page_num: int) -> dict:
    """按名称构建检测器实例。"""
    dets = {}
    if "baseline" in names:
        dets["baseline"] = BaselineDetector(BACKUP_DIR, page_num)
    if "rtdetr" in names:
        dets["rtdetr-v2"] = RTDetrDetector(conf_threshold=0.3)
    if "koharu" in names:
        dets["koharu-ctd"] = KoharuSingleDetector(engine="comic-text-detector")
    if "ctd" in names:
        dets["ctd-onnx"] = CtdDetector()
    return dets


def crop_and_ocr(img: np.ndarray, blocks: list[dict], tag: str, page_num: int) -> tuple[list[dict], float]:
    if not blocks:
        return [], 0.0
    h, w = img.shape[:2]
    crop_paths = []
    for i, b in enumerate(blocks):
        x1 = max(0, int(b["bbox"][0]))
        y1 = max(0, int(b["bbox"][1]))
        x2 = min(w, int(b["bbox"][2]))
        y2 = min(h, int(b["bbox"][3]))
        if x2 <= x1 or y2 <= y1:
            b["ocr_text"] = ""
            b["_skip"] = True
            continue
        crop = img[y1:y2, x1:x2]
        ch, cw = crop.shape[:2]
        if cw < 20 or ch < 20:
            scale = max(20 / cw, 20 / ch, 1.0)
            crop = cv2.resize(crop, (int(cw * scale), int(ch * scale)), interpolation=cv2.INTER_CUBIC)
        cp = CROP_DIR / f"p{page_num}_{tag}_{i:03d}.png"
        cv2.imwrite(str(cp), crop)
        b["_crop_path"] = str(cp)
        crop_paths.append(str(cp))
    t0 = time.perf_counter()
    results = ocr_batch(crop_paths, engine="baberu")
    ocr_time = time.perf_counter() - t0
    ocr_map = {r["crop"]: r.get("ocr", "") for r in results}
    for b in blocks:
        if b.get("_skip"):
            continue
        b["ocr_text"] = ocr_map.get(b.get("_crop_path", ""), "").strip()
    return blocks, ocr_time


def deduplicate(blocks: list[dict], iou_thresh: float = 0.5) -> tuple[list[dict], int]:
    if not blocks:
        return [], 0
    kept = []
    merged = 0
    for b in blocks:
        dup = None
        for k in kept:
            if _iou(b["bbox"], k["bbox"]) > iou_thresh:
                dup = k
                break
        if dup:
            merged += 1
            if len(b.get("ocr_text", "")) > len(dup.get("ocr_text", "")):
                dup["ocr_text"] = b["ocr_text"]
                dup["bbox"] = b["bbox"]
        else:
            kept.append(dict(b))
    return kept, merged


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def calc_metrics(blocks_raw: list[dict], blocks_dedup: list[dict],
                 merged: int, ocr_time: float, detect_time: float | None) -> dict:
    total = len(blocks_raw)
    non_empty = sum(1 for b in blocks_raw if b.get("ocr_text", ""))
    raw_chars = sum(len(b.get("ocr_text", "")) for b in blocks_raw)
    dedup_chars = sum(len(b.get("ocr_text", "")) for b in blocks_dedup)
    widths = [b["bbox"][2] - b["bbox"][0] for b in blocks_raw]
    heights = [b["bbox"][3] - b["bbox"][1] for b in blocks_raw]
    chars_per = [len(b.get("ocr_text", "")) for b in blocks_raw if b.get("ocr_text", "")]
    return {
        "n_boxes": total,
        "non_empty_boxes": non_empty,
        "non_empty_rate": round(non_empty / total, 3) if total else 0.0,
        "raw_chars": raw_chars,
        "dedup_chars": dedup_chars,
        "merged_duplicates": merged,
        "avg_chars_per_nonempty": round(sum(chars_per) / len(chars_per), 1) if chars_per else 0.0,
        "box_width_range": [round(min(widths), 1), round(max(widths), 1)] if widths else [0, 0],
        "box_height_range": [round(min(heights), 1), round(max(heights), 1)] if heights else [0, 0],
        "ocr_time_sec": round(ocr_time, 2),
        "detect_time_sec": round(detect_time, 2) if detect_time is not None else None,
        "ocr_results": [
            {"bbox": [round(v, 1) for v in b["bbox"]], "text": b.get("ocr_text", "")[:120]}
            for b in blocks_dedup if b.get("ocr_text", "")
        ],
    }


def compare_page(page_num: int, detector_names: list[str]) -> dict:
    raw_path = RAW_DIR / f"{page_num}.jpg"
    if not raw_path.exists():
        return {"page": page_num, "error": f"not found: {raw_path}"}
    img = cv2.imdecode(np.fromfile(str(raw_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"page": page_num, "error": f"cannot read: {raw_path}"}
    img_h, img_w = img.shape[:2]

    detectors = build_detectors(detector_names, page_num)
    page_result = {"page": page_num, "image_size": [img_w, img_h], "detectors": {}}

    for name, det in detectors.items():
        print(f"  [{name}] detecting...", flush=True)
        blocks, detect_time = det.detect(img)
        print(f"  [{name}] {len(blocks)} boxes ({detect_time:.2f}s), running OCR...", flush=True)
        blocks, ocr_time = crop_and_ocr(img, blocks, name, page_num)
        dedup, merged = deduplicate(blocks)
        page_result["detectors"][name] = calc_metrics(blocks, dedup, merged, ocr_time, detect_time)
        print(f"  [{name}] {len(blocks)} boxes, {page_result['detectors'][name]['dedup_chars']} chars", flush=True)

    return page_result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="+", type=int, default=[11, 13, 14, 17, 18])
    ap.add_argument("--detectors", nargs="+", default=["baseline", "rtdetr"],
                    choices=["baseline", "rtdetr", "koharu", "ctd"])
    args = ap.parse_args()

    print(f"[detect-multi] pages={args.pages}, detectors={args.detectors}")
    results = []
    for p in args.pages:
        print(f"\n=== page_{p} ===")
        r = compare_page(p, args.detectors)
        if "error" in r:
            print(f"  ERROR: {r['error']}")
        results.append(r)

    valid = [r for r in results if "error" not in r]
    summary = {"pages": args.pages, "detectors": args.detectors, "per_page": results}
    if valid:
        det_names = list(valid[0]["detectors"].keys())
        agg = {}
        for dn in det_names:
            agg[dn] = {
                "total_boxes": sum(r["detectors"][dn]["n_boxes"] for r in valid),
                "total_chars": sum(r["detectors"][dn]["dedup_chars"] for r in valid),
                "avg_nonempty_rate": round(
                    sum(r["detectors"][dn]["non_empty_rate"] for r in valid) / len(valid), 3),
                "avg_detect_time": round(
                    sum(r["detectors"][dn].get("detect_time_sec") or 0 for r in valid) / len(valid), 2),
            }
        summary["aggregate"] = agg

    out = OUT_DIR / "results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n[detect-multi] -> {out}")
    if "aggregate" in summary:
        for dn, m in summary["aggregate"].items():
            print(f"  {dn}: {m['total_boxes']} boxes, {m['total_chars']} chars")


if __name__ == "__main__":
    main()
