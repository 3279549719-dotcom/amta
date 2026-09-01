"""Run page 14 and 18 with fixed context+glossary injection (production minimal path)."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from amta.stage3_minimal import translate_page_minimal, build_prefetch_context  # noqa: E402
from amta import workstate  # noqa: E402

WORK_ID = "touhou-single-wing"
STATE_DIR = ROOT / "workspace/touhou-single-wing"
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
CANON_DIR = ROOT / "output/data/stage3_full_canon"
OUT_DIR = ROOT / "output/data/fix_context_glossary_p14p18"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGES = [18]  # page 14 already done, re-run page 18 only
results = {}

for page in PAGES:
    canon_path = CANON_DIR / f"page_{page}_canon.json"
    raw_path = RAW_DIR / f"{page}.jpg"
    out_path = OUT_DIR / f"page_{page}_translation.json"

    canon = json.load(open(canon_path, encoding="utf-8"))
    canon_items = [item for item in canon["items"]
                   if (item.get("baberu_text") or item.get("text") or "").strip()]

    # Capture prefetch context evidence (with vlm_result=None to show raw context+glossary)
    ws = workstate.load_state(WORK_ID)
    prefetch = build_prefetch_context(canon_items, ws, STATE_DIR, None)

    print(f"\n=== page_{page} ===")
    print(f"  canon items: {len(canon_items)}")
    print(f"  system_extra length: {len(prefetch['system_extra'])}")
    print(f"  system_extra preview: {prefetch['system_extra'][:300]}")
    print(f"  context_prefix length: {len(prefetch['context_prefix'])}")
    print(f"  context_prefix preview: {prefetch['context_prefix'][:300]}")
    print(f"  refined_canon count: {len(prefetch['refined_canon'])}")

    # Run full production translation (VLM refine + context + glossary + plain translate)
    t0 = time.perf_counter()
    result = translate_page_minimal(
        WORK_ID, canon_items,
        raw_image_path=str(raw_path),
        state_dir=str(STATE_DIR),
        page=str(page),
    )
    elapsed = time.perf_counter() - t0

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    translations = result.get("translations", {})
    n_holes = sum(1 for v in translations.values() if not v.strip())

    results[page] = {
        "n_canon": len(canon_items),
        "n_translations": len(translations),
        "n_holes": n_holes,
        "glossary_violations": result.get("glossary_violations", []),
        "residue": result.get("residue", []),
        "vlm_refine": result.get("vlm_refine", {}),
        "elapsed": round(elapsed, 1),
        "prefetch_evidence": {
            "system_extra": prefetch["system_extra"],
            "context_prefix": prefetch["context_prefix"],
            "refined_canon_count": len(prefetch["refined_canon"]),
        },
        "translations": translations,
    }

    print(f"  translations: {len(translations)}")
    print(f"  holes: {n_holes}")
    print(f"  glossary violations: {len(results[page]['glossary_violations'])}")
    print(f"  residue: {len(results[page]['residue'])}")
    print(f"  vlm_refine: {results[page]['vlm_refine']}")
    print(f"  elapsed: {elapsed:.1f}s")
    for rid, t in list(translations.items())[:5]:
        print(f"    {rid}: {t[:60]}")

summary_path = OUT_DIR / "run_summary.json"
summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nSummary saved to {summary_path}")
