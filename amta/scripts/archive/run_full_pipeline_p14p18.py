"""Full pipeline for page 14/18: detect (with label) → OCR → rule filter → VLM tri-state → translate.

Branch: feat/detect-label-fullrun-p14p18
Conf: 0.3 (V2 best)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from detect_rtdetr import RTDetrDetector  # noqa: E402
from _02_ocr import run as ocr_run  # noqa: E402
from exp_guardrails_v2 import rule_filter, vlm_filter_v2  # noqa: E402
from amta.stage3_minimal import translate_page_minimal  # noqa: E402

# === Config ===
WORK_ID = "touhou-single-wing"
STATE_DIR = ROOT / "workspace/touhou-single-wing"
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT_DIR = ROOT / "output/data/fullrun_label_vlm_p14p18"
DET_DIR = OUT_DIR / "detection"
OCR_DIR = OUT_DIR / "ocr"
TRANS_DIR = OUT_DIR / "translation"
for d in [OUT_DIR, DET_DIR, OCR_DIR, TRANS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

PAGES = [14, 18]
CONF_THRESHOLD = 0.3
OCR_ENGINE = "baberu"


def detect_page(detector, page, raw_path):
    """Run detection, save in load_detection-compatible format."""
    blocks = detector.detect(str(raw_path), conf_threshold=CONF_THRESHOLD)
    det_doc = {
        "work_id": WORK_ID,
        "page": str(page),
        "source": str(raw_path),
        "blocks": blocks,
    }
    det_path = DET_DIR / f"page_{page}_detection.json"
    det_path.write_text(json.dumps(det_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return blocks, det_path


def ocr_page(page, det_path, raw_path):
    """Run OCR, return canon doc."""
    canon_path = OCR_DIR / f"page_{page}_canon.json"
    doc = ocr_run(
        work_id=WORK_ID,
        det_path=det_path,
        raw_page=raw_path,
        out_path=canon_path,
        page_idx=page,
        engine=OCR_ENGINE,
        vlm_enabled=False,
    )
    return doc, canon_path


def canon_to_blocks(canon_doc):
    """Convert canon items to blocks for rule_filter + vlm_filter."""
    items = canon_doc.get("items", [])
    blocks = []
    for i, item in enumerate(items):
        text = item.get("baberu_text", "") or item.get("text", "")
        bbox = item.get("bbox", [0, 0, 0, 0])
        blocks.append({
            "bbox": bbox,
            "text": text,
            "region_id": item.get("region_id", f"r{i:02d}"),
            "bubble_type": item.get("bubble_type", "unknown"),
            "_idx": i,
        })
    return blocks


def build_canon_for_translate(filtered_blocks, page):
    """Build canon items from filtered blocks for translate_page_minimal."""
    items = []
    for i, b in enumerate(filtered_blocks):
        items.append({
            "region_id": f"page_{page}_u{i:02d}",
            "bbox": b["bbox"],
            "baberu_text": b.get("text", ""),
            "page": page,
            "bubble_type": b.get("bubble_type", "unknown"),
            "source_engines": ["rtdetr-v2", "baberu"],
            "vlm_state": b.get("filter_reason", "keep"),
        })
    return items


def run_full_pipeline():
    print("=" * 70)
    print(f"FULL PIPELINE: detect(label) → OCR({OCR_ENGINE}) → rule → VLM(conf={CONF_THRESHOLD}) → translate")
    print(f"Pages: {PAGES}")
    print("=" * 70)

    detector = RTDetrDetector(conf_threshold=CONF_THRESHOLD)
    all_results = {}

    for page in PAGES:
        raw_path = RAW_DIR / f"{page}.jpg"
        if not raw_path.exists():
            print(f"\n[SKIP] page {page}: raw image not found")
            continue

        print(f"\n{'='*50}")
        print(f"PAGE {page}")
        print(f"{'='*50}")

        # Step 1: Detect
        print(f"\n[1/5] DETECT (conf={CONF_THRESHOLD})...")
        t0 = time.perf_counter()
        det_blocks, det_path = detect_page(detector, page, raw_path)
        det_time = time.perf_counter() - t0
        from collections import Counter
        bt = Counter(b["bubble_type"] for b in det_blocks)
        confs = [b["confidence"] for b in det_blocks]
        print(f"  {len(det_blocks)} boxes in {det_time:.1f}s")
        print(f"  bubble_types: {dict(bt)}")
        print(f"  conf: min={min(confs):.3f} max={max(confs):.3f} avg={sum(confs)/len(confs):.3f}")

        # Step 2: OCR
        print(f"\n[2/5] OCR ({OCR_ENGINE})...")
        t0 = time.perf_counter()
        try:
            canon_doc, canon_path = ocr_page(page, det_path, raw_path)
            ocr_time = time.perf_counter() - t0
            n_ocr = canon_doc.get("n_regions", len(canon_doc.get("items", [])))
            print(f"  {n_ocr} regions in {ocr_time:.1f}s")
        except Exception as e:
            ocr_time = time.perf_counter() - t0
            print(f"  OCR FAIL in {ocr_time:.1f}s: {type(e).__name__}: {e}")
            all_results[page] = {"status": "ocr_error", "error": str(e)}
            continue

        # Get image dimensions for rule filter
        img = cv2.imdecode(np.fromfile(str(raw_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        img_h, img_w = img.shape[:2]

        # Step 3: Rule filter
        print(f"\n[3/5] RULE FILTER...")
        blocks = canon_to_blocks(canon_doc)
        print(f"  input: {len(blocks)} blocks, image {img_w}x{img_h}")
        kept, rule_removed = rule_filter(blocks, img_w, img_h)
        print(f"  kept: {len(kept)}, removed: {len(rule_removed)}")
        for b in rule_removed:
            print(f"    REMOVED: '{b.get('text','')[:30]}' reason={b.get('filter_reason','')}")

        # Step 4: VLM tri-state filter
        print(f"\n[4/5] VLM TRI-STATE FILTER...")
        t0 = time.perf_counter()
        vlm_kept, vlm_fixed, vlm_dropped = vlm_filter_v2(raw_path, kept)
        vlm_time = time.perf_counter() - t0
        print(f"  keep={len(vlm_kept)}, fix={len(vlm_fixed)}, drop={len(vlm_dropped)} in {vlm_time:.1f}s")

        # Merge keep + fix for translation
        final_blocks = vlm_kept + vlm_fixed
        print(f"  final (keep+fix): {len(final_blocks)} blocks → translate")

        # Step 5: Translate
        print(f"\n[5/5] TRANSLATE (formal minimal + glossary + context)...")
        canon_items = build_canon_for_translate(final_blocks, page)
        t0 = time.perf_counter()
        try:
            result = translate_page_minimal(
                WORK_ID, canon_items,
                raw_image_path=str(raw_path),
                state_dir=str(STATE_DIR),
                page=str(page),
            )
            trans_time = time.perf_counter() - t0
            translations = result.get("translations", {})
            n_holes = sum(1 for v in translations.values() if not v.strip())
            n_residue = len(result.get("residue", []))
            n_glossary = len(result.get("glossary_violations", []))
            vlm_refine = result.get("vlm_refine", {})
            print(f"  {len(translations)} translations in {trans_time:.1f}s")
            print(f"  holes={n_holes}, residue={n_residue}, glossary_violations={n_glossary}")
            print(f"  VLM OCR refine: {vlm_refine.get('refinement_count', 0)} fixes")

            # Save translation
            trans_path = TRANS_DIR / f"page_{page}_translation.json"
            trans_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

            # Save full page result
            page_result = {
                "page": page,
                "status": "ok",
                "detect": {
                    "n_boxes": len(det_blocks),
                    "bubble_types": dict(bt),
                    "conf_range": [min(confs), max(confs)],
                    "time": round(det_time, 1),
                },
                "ocr": {
                    "n_regions": n_ocr,
                    "engine": OCR_ENGINE,
                    "time": round(ocr_time, 1),
                },
                "rule_filter": {
                    "input": len(blocks),
                    "kept": len(kept),
                    "removed": len(rule_removed),
                    "removed_details": [{"text": b.get("text", "")[:50], "reason": b.get("filter_reason", "")} for b in rule_removed],
                },
                "vlm_filter": {
                    "keep": len(vlm_kept),
                    "fix": len(vlm_fixed),
                    "drop": len(vlm_dropped),
                    "dropped_details": [{"text": b.get("text", "")[:50], "reason": b.get("filter_reason", "")} for b in vlm_dropped],
                    "fixed_details": [{"original": b.get("original_text", "")[:50], "corrected": b.get("text", "")[:50]} for b in vlm_fixed],
                    "time": round(vlm_time, 1),
                },
                "translate": {
                    "n_translations": len(translations),
                    "n_final_blocks": len(final_blocks),
                    "holes": n_holes,
                    "residue": n_residue,
                    "glossary_violations": n_glossary,
                    "vlm_refine": vlm_refine,
                    "time": round(trans_time, 1),
                },
                "translations": translations,
                "final_blocks": [
                    {
                        "bbox": b["bbox"],
                        "text": b.get("text", ""),
                        "original_text": b.get("original_text", ""),
                        "bubble_type": b.get("bubble_type", "unknown"),
                        "vlm_state": "fixed" if "original_text" in b else "keep",
                        "translation": translations.get(f"page_{page}_u{final_blocks.index(b):02d}", ""),
                    }
                    for b in final_blocks
                ],
            }
            all_results[page] = page_result

        except Exception as e:
            trans_time = time.perf_counter() - t0
            print(f"  TRANSLATE FAIL in {trans_time:.1f}s: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            all_results[page] = {"status": "translate_error", "error": str(e)}

    # Save summary
    summary_path = OUT_DIR / "full_pipeline_summary.json"
    summary_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'='*70}")
    print(f"SUMMARY saved to {summary_path}")
    for page, r in all_results.items():
        if r.get("status") == "ok":
            print(f"  page {page}: detect={r['detect']['n_boxes']} ocr={r['ocr']['n_regions']} "
                  f"rule_kept={r['rule_filter']['kept']} vlm(keep={r['vlm_filter']['keep']} "
                  f"fix={r['vlm_filter']['fix']} drop={r['vlm_filter']['drop']}) "
                  f"trans={r['translate']['n_translations']} holes={r['translate']['holes']}")
        else:
            print(f"  page {page}: {r.get('status')} - {r.get('error','')}")


if __name__ == "__main__":
    run_full_pipeline()
