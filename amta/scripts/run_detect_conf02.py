"""v3 实验前置：RT-DETR-v2 conf=0.2 检测 + Baberu OCR，只跑 10 页样本。

v3 = 三态 VLM + 检测层降阈值（conf=0.2），目标是召回更多无框字（如 page_05 的正文）。
本脚本只做检测 + OCR，输出到 output/data/detect_conf02/results.json。
后续用 exp_guardrails_v2.py 的逻辑（改输入路径）跑三态 VLM + LM 翻译。
"""
from __future__ import annotations

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
OUT_DIR = ROOT / "output" / "data" / "detect_conf02"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CROP_DIR = OUT_DIR / "crops"
CROP_DIR.mkdir(exist_ok=True)

SAMPLE_PAGES = [0, 1, 2, 5, 6, 11, 12, 14, 18, 32]
CONF_THRESHOLD = 0.2  # v3 降阈值，从 0.3 降到 0.2


def crop_and_ocr(img, blocks, page_num):
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
        cp = CROP_DIR / f"p{page_num}_{i:03d}.png"
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


def main():
    print(f"[detect-conf02] {len(SAMPLE_PAGES)} pages, RT-DETR-v2 conf={CONF_THRESHOLD} + Baberu OCR")
    det = RTDetrDetector(conf_threshold=CONF_THRESHOLD)
    det._load()
    print("[detect-conf02] model loaded.")

    results = []
    t_total = time.perf_counter()
    for p in SAMPLE_PAGES:
        raw_path = RAW_DIR / f"{p}.jpg"
        if not raw_path.exists():
            print(f"  page_{p}: NOT FOUND, skip")
            results.append({"page": p, "error": "not found"})
            continue
        img = cv2.imdecode(np.fromfile(str(raw_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            results.append({"page": p, "error": "cannot read"})
            continue
        img_h, img_w = img.shape[:2]

        t0 = time.perf_counter()
        blocks = det.detect(img)
        detect_time = time.perf_counter() - t0

        blocks, ocr_time = crop_and_ocr(img, blocks, p)
        non_empty = sum(1 for b in blocks if b.get("ocr_text", ""))
        raw_chars = sum(len(b.get("ocr_text", "")) for b in blocks)

        results.append({
            "page": p,
            "image_size": [img_w, img_h],
            "n_boxes": len(blocks),
            "non_empty_boxes": non_empty,
            "raw_chars": raw_chars,
            "detect_time_sec": round(detect_time, 2),
            "ocr_time_sec": round(ocr_time, 2),
            "ocr_results": [
                {"bbox": [round(v, 1) for v in b["bbox"]], "text": b.get("ocr_text", "")[:120], "confidence": b.get("confidence", 0)}
                for b in blocks if b.get("ocr_text", "")
            ],
        })
        print(f"  page_{p:02d}: {len(blocks):2d} boxes, {raw_chars:4d} chars, "
              f"non_empty={non_empty}, det={detect_time:.2f}s, ocr={ocr_time:.2f}s", flush=True)

    elapsed = time.perf_counter() - t_total
    valid = [r for r in results if "error" not in r]
    agg = {
        "conf_threshold": CONF_THRESHOLD,
        "pages_total": len(SAMPLE_PAGES),
        "pages_ok": len(valid),
        "total_boxes": sum(r["n_boxes"] for r in valid),
        "total_chars": sum(r["raw_chars"] for r in valid),
        "avg_boxes_per_page": round(sum(r["n_boxes"] for r in valid) / len(valid), 1),
        "avg_chars_per_page": round(sum(r["raw_chars"] for r in valid) / len(valid), 1),
        "elapsed_sec": round(elapsed, 1),
    }

    out = OUT_DIR / "results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"aggregate": agg, "per_page": results}, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"[detect-conf02] DONE in {elapsed:.1f}s")
    print(f"  Pages: {agg['pages_ok']}/{agg['pages_total']} OK")
    print(f"  Total: {agg['total_boxes']} boxes, {agg['total_chars']} chars")
    print(f"  Avg:   {agg['avg_boxes_per_page']} boxes/page, {agg['avg_chars_per_page']} chars/page")
    print(f"  -> {out}")


if __name__ == "__main__":
    main()
