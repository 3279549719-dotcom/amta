"""检测方案 A/B 对比：现有4引擎并集 vs RT-DETR-v2。

复用项目已有接口：
- 检测: scripts/detect_rtdetr.py (RT-DETR-v2) + backup 历史结果 (baseline)
- OCR: amta.ocr_engines.ocr_batch(engine="baberu")

用法:
    python scripts/run_detect_ab.py --pages 11 13 14 17 18
输出:
    output/data/detect_ab/results.json
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
from detect_rtdetr import RTDetrDetector  # noqa: E402

RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
BACKUP_DIR = ROOT / "output" / "backup" / "2026-08-27-pre-rerun-11-20"
OUT_DIR = ROOT / "output" / "data" / "detect_ab"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CROP_DIR = OUT_DIR / "crops"
CROP_DIR.mkdir(exist_ok=True)


def load_baseline(page_num: int) -> list[dict]:
    path = BACKUP_DIR / f"page_{page_num}_detection.json"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    blocks = []
    for b in d.get("blocks", []):
        bb = b.get("bbox")
        if bb and len(bb) == 4:
            blocks.append({"bbox": [float(v) for v in bb], "source": "baseline"})
    return blocks


def crop_and_ocr(img: np.ndarray, blocks: list[dict], tag: str, page_num: int) -> tuple[list[dict], float]:
    """裁剪每个框 → 存临时图 → baberu OCR → 返回带 ocr_text 的 blocks。"""
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
        cp = b.get("_crop_path", "")
        b["ocr_text"] = ocr_map.get(cp, "").strip()
    return blocks, ocr_time


def deduplicate(blocks: list[dict], iou_thresh: float = 0.5) -> tuple[list[dict], int]:
    """按空间位置去重 OCR 结果，保留文字最长的。"""
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


def compare_page(page_num: int, det: RTDetrDetector) -> dict:
    raw_path = RAW_DIR / f"{page_num}.jpg"
    if not raw_path.exists():
        return {"page": page_num, "error": f"not found: {raw_path}"}
    # cv2.imread 不支持中文路径
    img = cv2.imdecode(np.fromfile(str(raw_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"page": page_num, "error": f"cannot read: {raw_path}"}
    img_h, img_w = img.shape[:2]

    # baseline: 从 backup 加载（检测时间不可得）
    blocks_a = load_baseline(page_num)
    blocks_a, ocr_time_a = crop_and_ocr(img, blocks_a, "baseline", page_num)

    # rtdetr: 实时检测
    t0 = time.perf_counter()
    blocks_b = det.detect(img)
    detect_time_b = time.perf_counter() - t0
    blocks_b = [{"bbox": b["bbox"], "source": "rtdetr"} for b in blocks_b]
    blocks_b, ocr_time_b = crop_and_ocr(img, blocks_b, "rtdetr", page_num)

    # 去重
    dedup_a, merged_a = deduplicate(blocks_a)
    dedup_b, merged_b = deduplicate(blocks_b)

    return {
        "page": page_num,
        "image_size": [img_w, img_h],
        "baseline": calc_metrics(blocks_a, dedup_a, merged_a, ocr_time_a, None),
        "rtdetr": calc_metrics(blocks_b, dedup_b, merged_b, ocr_time_b, detect_time_b),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="+", type=int, default=[11, 13, 14, 17, 18])
    ap.add_argument("--conf", type=float, default=0.3)
    args = ap.parse_args()

    print(f"[detect-ab] pages={args.pages}, conf={args.conf}")
    print("[detect-ab] loading RT-DETR-v2 ...")
    det = RTDetrDetector(conf_threshold=args.conf)
    det._load()
    print("[detect-ab] ready.")

    results = []
    for p in args.pages:
        print(f"\n=== page_{p} ===")
        r = compare_page(p, det)
        if "error" in r:
            print(f"  ERROR: {r['error']}")
        else:
            print(f"  baseline: {r['baseline']['n_boxes']} boxes, {r['baseline']['dedup_chars']} chars, "
                  f"non_empty={r['baseline']['non_empty_rate']}")
            print(f"  rtdetr:   {r['rtdetr']['n_boxes']} boxes, {r['rtdetr']['dedup_chars']} chars, "
                  f"non_empty={r['rtdetr']['non_empty_rate']}, detect={r['rtdetr']['detect_time_sec']}s")
        results.append(r)

    valid = [r for r in results if "error" not in r]
    summary = {"pages": args.pages, "conf_threshold": args.conf, "per_page": results}
    if valid:
        summary["aggregate"] = {
            "baseline_total_boxes": sum(r["baseline"]["n_boxes"] for r in valid),
            "rtdetr_total_boxes": sum(r["rtdetr"]["n_boxes"] for r in valid),
            "baseline_total_chars": sum(r["baseline"]["dedup_chars"] for r in valid),
            "rtdetr_total_chars": sum(r["rtdetr"]["dedup_chars"] for r in valid),
            "baseline_avg_nonempty": round(sum(r["baseline"]["non_empty_rate"] for r in valid) / len(valid), 3),
            "rtdetr_avg_nonempty": round(sum(r["rtdetr"]["non_empty_rate"] for r in valid) / len(valid), 3),
            "rtdetr_avg_detect_time": round(sum(r["rtdetr"]["detect_time_sec"] or 0 for r in valid) / len(valid), 2),
            "char_improvement_pct": round(
                (sum(r["rtdetr"]["dedup_chars"] for r in valid) - sum(r["baseline"]["dedup_chars"] for r in valid))
                / max(1, sum(r["baseline"]["dedup_chars"] for r in valid)) * 100, 1),
        }

    out = OUT_DIR / "results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n[detect-ab] -> {out}")
    if "aggregate" in summary:
        a = summary["aggregate"]
        print(f"  baseline: {a['baseline_total_boxes']} boxes, {a['baseline_total_chars']} chars")
        print(f"  rtdetr:   {a['rtdetr_total_boxes']} boxes, {a['rtdetr_total_chars']} chars")
        print(f"  char improvement: +{a['char_improvement_pct']}%")


if __name__ == "__main__":
    main()
