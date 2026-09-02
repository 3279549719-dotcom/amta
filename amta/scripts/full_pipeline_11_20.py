"""Batch OCR pages p11-p20 using detect_contract full boxes, then translate with minimal mode.

detect_contract/p{N}.json → JPG N.jpg → canon page_{N-1} (off-by-one confirmed).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from _02_ocr import run as ocr_run  # noqa: E402
from _03_translate import run as translate_run  # noqa: E402

DETECT_DIR = ROOT / "output/data/detect_contract"
RAW_IMAGE_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
CANON_DIR = ROOT / "output/data/stage3_full_canon"
TRANS_DIR = ROOT / "output/data/stage3_full_translation"
STATE_DIR = ROOT / "workspace/touhou-single-wing"

CANON_DIR.mkdir(parents=True, exist_ok=True)
TRANS_DIR.mkdir(parents=True, exist_ok=True)

results = []

for det_page in range(11, 21):  # p11 to p20 → JPG N → canon page N (page_N = N.jpg, 对齐)
    canon_page = det_page  # page_N = N.jpg (修正 off-by-one)
    det_path = DETECT_DIR / f"p{det_page}.json"
    raw_path = RAW_IMAGE_DIR / f"{det_page}.jpg"
    canon_path = CANON_DIR / f"page_{canon_page}_canon.json"
    trans_path = TRANS_DIR / f"page_{canon_page}_translation.json"

    if not det_path.exists():
        print(f"[SKIP] p{det_page}: detection not found")
        continue
    if not raw_path.exists():
        print(f"[SKIP] p{det_page}: image {raw_path} not found")
        continue

    # Step 1: OCR
    print(f"[OCR] p{det_page} (JPG {det_page}.jpg) → canon page_{canon_page}...")
    t0 = time.perf_counter()
    try:
        doc = ocr_run(
            work_id="touhou-single-wing",
            det_path=det_path,
            raw_page=raw_path,
            out_path=canon_path,
            page_idx=canon_page,
            engine="dashscope",
            vlm_enabled=False,
        )
        ocr_time = time.perf_counter() - t0
        n_regions = doc.get("n_regions", 0)
        print(f"  OCR OK in {ocr_time:.1f}s — {n_regions} regions")
    except Exception as e:
        ocr_time = time.perf_counter() - t0
        print(f"  OCR FAIL in {ocr_time:.1f}s — {type(e).__name__}: {e}")
        results.append({"det_page": det_page, "canon_page": canon_page, "status": "ocr_error", "error": str(e)})
        continue

    # Step 2: Translate
    print(f"[TRANS] page_{canon_page} → minimal mode...")
    t0 = time.perf_counter()
    try:
        translate_run(
            str(canon_path), str(trans_path),
            work_id="touhou-single-wing",
            state_dir=str(STATE_DIR),
            mode="minimal",
            raw_image_path=str(raw_path),
        )
        trans_time = time.perf_counter() - t0

        result = json.loads(trans_path.read_text(encoding="utf-8"))
        translations = result.get("translations", {})
        holes = sum(1 for v in translations.values() if not v.strip())
        residue = len(result.get("residue", []))
        glossary = len(result.get("glossary_violations", []))
        vlm = result.get("vlm_refine", {})

        print(f"  TRANS OK in {trans_time:.1f}s — {len(translations)} translations, "
              f"{holes} holes, {residue} residue, {glossary} glossary, "
              f"VLM: {vlm.get('refinement_count', 0)} refine")

        results.append({
            "det_page": det_page,
            "canon_page": canon_page,
            "jpg": det_page,
            "n_regions": n_regions,
            "n_translations": len(translations),
            "holes": holes,
            "residue": residue,
            "glossary_violations": glossary,
            "ocr_time": ocr_time,
            "trans_time": trans_time,
            "vlm_refine": vlm,
            "status": "ok",
        })
    except Exception as e:
        trans_time = time.perf_counter() - t0
        print(f"  TRANS FAIL in {trans_time:.1f}s — {type(e).__name__}: {e}")
        results.append({
            "det_page": det_page, "canon_page": canon_page,
            "n_regions": n_regions, "status": "trans_error", "error": str(e),
        })

# Summary
print("\n" + "=" * 70)
print("FULL PIPELINE SUMMARY (detect_contract boxes → OCR → minimal translate)")
print("=" * 70)
ok = [r for r in results if r["status"] == "ok"]
errors = [r for r in results if r["status"] != "ok"]
print(f"Pages: {len(results)} total, {len(ok)} ok, {len(errors)} errors")
if ok:
    total_regions = sum(r["n_regions"] for r in ok)
    total_holes = sum(r["holes"] for r in ok)
    total_residue = sum(r["residue"] for r in ok)
    total_ocr = sum(r["ocr_time"] for r in ok)
    total_trans = sum(r["trans_time"] for r in ok)
    print(f"Total regions: {total_regions} (vs backup canon 62 — was missing {total_regions-62})")
    print(f"Total holes: {total_holes}")
    print(f"Total residue: {total_residue}")
    print(f"Total OCR time: {total_ocr:.1f}s")
    print(f"Total translate time: {total_trans:.1f}s")

summary_path = TRANS_DIR / "full_pipeline_summary.json"
summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nSummary saved to {summary_path}")
