"""One-off: extract katakana names from tagatame OCR text via LLM.

Reuses existing canon artifacts from multiple work-ids (they cover different
page ranges — no single work-id has the whole book). Merges all OCR text,
sends to LLM for name extraction, saves to book-level glossary store.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from amta.stores import artifacts
from amta.common.book_store import book_id_from_src_dir, save_glossary, save_meta
from amta.guards.name_pre_scan import build_extraction_prompt, parse_extraction_response

SRC_DIR = r"D:\我的汉化\汉化作品\东方\タガタメ"

# Work-ids that have canon files for tagatame (different page ranges)
WORK_IDS_WITH_CANON = [
    "gui-1790855929797",   # p1-9
    "gui-1791349022696",   # p42-44
    "tagatame-p33-p38-fix", # p33, p38
    "gui-1791218772775",   # p1-18 (most complete)
]


def collect_all_ocr_text() -> tuple[str, list[int]]:
    """Collect OCR text from all work-ids' canon files. Returns (combined_text, pages_covered)."""
    all_text_parts: list[str] = []
    pages_seen: set[int] = set()

    for wid in WORK_IDS_WITH_CANON:
        art_dir = ROOT / "workspace" / wid / "artifacts"
        canon_dir = art_dir / "canon"
        if not canon_dir.exists():
            print(f"  [skip] {wid}: no canon dir")
            continue

        canon_files = sorted(canon_dir.glob("page_*.json"))
        print(f"  {wid}: {len(canon_files)} canon files")

        for cf in canon_files:
            # Extract page number from filename: page_3.json -> 3
            page_num = int(cf.stem.split("_")[1])
            if page_num in pages_seen:
                continue  # already got this page from another work-id
            pages_seen.add(page_num)

            try:
                doc = artifacts.load_canon(cf)
                for item in doc.get("items", []):
                    txt = item.get("baberu_text") or item.get("text") or ""
                    if txt.strip():
                        all_text_parts.append(txt)
            except Exception as e:
                print(f"    [warn] {cf.name}: {e}")
                continue

    combined = "\n".join(all_text_parts)
    return combined, sorted(pages_seen)


def main():
    print("=== Collecting OCR text from existing canon artifacts ===")
    combined_text, pages = collect_all_ocr_text()
    print(f"\nCollected {len(combined_text)} chars of OCR text")
    print(f"Pages covered: {pages}")

    if not combined_text:
        print("ERROR: no OCR text found!")
        sys.exit(1)

    # LLM extraction
    print("\n=== Running LLM name extraction ===")
    from amta.backends.chat_client import chat_text
    from amta.translation.translate import get_chat_config

    cfg = get_chat_config()
    prompt = build_extraction_prompt(combined_text)
    print(f"Prompt length: {len(prompt)} chars")

    resp = chat_text(
        cfg["base_url"], cfg["model"],
        [{"role": "user", "content": prompt}],
        api_key=cfg["api_key"],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    names = parse_extraction_response(resp)
    print(f"\nExtracted {len(names)} names:")
    for surface, translation in sorted(names.items()):
        print(f"  {surface} -> {translation}")

    # Save to book-level store
    bid = book_id_from_src_dir(SRC_DIR)
    save_meta(bid, SRC_DIR)
    save_glossary(bid, names)

    glossary_file = ROOT / "workspace" / "_books" / bid / "glossary.json"
    print(f"\nSaved to: {glossary_file}")
    print(f"book_id: {bid}")


if __name__ == "__main__":
    main()
