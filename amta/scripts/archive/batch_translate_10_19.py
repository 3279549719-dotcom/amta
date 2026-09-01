"""Batch translate pages 10-19 (JPG 11-20) with minimal mode.

page N (canon) → JPG N+1 (off-by-one, confirmed 2026-08-31).
"""
import json
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from _03_translate import run

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "output/backup/2026-08-27-pre-rerun-11-20"
OUT_DIR = ROOT / "output/data/stage3_minimal_batch"
RAW_IMAGE_DIR = r"D:\我的汉化\汉化作品\东方\单翼停留之地"
STATE_DIR = ROOT / "workspace/touhou-single-wing"

OUT_DIR.mkdir(parents=True, exist_ok=True)

results = []

for page_idx in range(10, 20):  # page_10 to page_19 → JPG 11-20
    jpg_num = page_idx + 1
    canon_path = BACKUP_DIR / f"page_{page_idx}_canon.json"
    out_path = OUT_DIR / f"page_{page_idx}_translation.json"
    raw_image = Path(RAW_IMAGE_DIR) / f"{jpg_num}.jpg"

    if not canon_path.exists():
        print(f"[SKIP] page_{page_idx}: canon not found")
        continue
    if not raw_image.exists():
        print(f"[SKIP] page_{page_idx}: image {raw_image} not found")
        continue

    canon = json.loads(canon_path.read_text(encoding="utf-8"))
    n_regions = len(canon) if isinstance(canon, list) else len(canon.get("items", []))

    print(f"[RUN] page_{page_idx} (JPG {jpg_num}.jpg), {n_regions} regions...")
    t0 = time.perf_counter()
    try:
        run(str(canon_path), str(out_path), work_id="touhou-single-wing",
            state_dir=str(STATE_DIR), mode="minimal", raw_image_path=str(raw_image))
        wall = time.perf_counter() - t0

        result = json.loads(out_path.read_text(encoding="utf-8"))
        translations = result.get("translations", {})
        holes = sum(1 for v in translations.values() if not v.strip())
        residue = len(result.get("residue", []))
        glossary = len(result.get("glossary_violations", []))
        vlm = result.get("vlm_refine", {})

        print(f"  OK in {wall:.1f}s — {len(translations)} translations, {holes} holes, "
              f"{residue} residue, {glossary} glossary, "
              f"VLM: {vlm.get('refinement_count', 0)} refine / {vlm.get('invalid_count', 0)} invalid / "
              f"{vlm.get('duplicate_count', 0)} dup")

        results.append({
            "page": page_idx,
            "jpg": jpg_num,
            "n_regions": n_regions,
            "wall_time": wall,
            "translations": len(translations),
            "holes": holes,
            "residue": residue,
            "glossary_violations": glossary,
            "vlm_refine": vlm,
            "status": "ok",
        })
    except Exception as e:
        wall = time.perf_counter() - t0
        print(f"  FAIL in {wall:.1f}s — {type(e).__name__}: {e}")
        results.append({
            "page": page_idx,
            "jpg": jpg_num,
            "n_regions": n_regions,
            "wall_time": wall,
            "status": "error",
            "error": str(e),
        })

# Summary
print("\n" + "=" * 60)
print("BATCH SUMMARY (minimal mode, pages 10-19)")
print("=" * 60)
ok = [r for r in results if r["status"] == "ok"]
errors = [r for r in results if r["status"] == "error"]
print(f"Pages: {len(results)} total, {len(ok)} ok, {len(errors)} errors")
if ok:
    total_regions = sum(r["n_regions"] for r in ok)
    total_holes = sum(r["holes"] for r in ok)
    total_residue = sum(r["residue"] for r in ok)
    total_glossary = sum(r["glossary_violations"] for r in ok)
    total_time = sum(r["wall_time"] for r in ok)
    print(f"Total regions: {total_regions}")
    print(f"Total holes: {total_holes} (target 0)")
    print(f"Total residue: {total_residue}")
    print(f"Total glossary violations: {total_glossary}")
    print(f"Total wall time: {total_time:.1f}s (avg {total_time/len(ok):.1f}s/page)")
    print(f"402 errors: {len(errors)}")

# Save summary
summary_path = OUT_DIR / "batch_summary.json"
summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nSummary saved to {summary_path}")
