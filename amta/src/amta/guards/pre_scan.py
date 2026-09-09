"""Pre-scan: build per-work locked terminology dictionary from all OCR text.

Run ONCE per work, before translation starts. Reads all canon artifacts,
collects all OCR text, matches against THBWiki master dictionary,
and writes confirmed terms to work_state.terms.

No LM calls — pure mechanical matching (exact + normalized + fuzzy ≤2).
Terms not in the master dict are left free (LLM translates them naturally;
one-off terms don't have consistency issues anyway).
"""
from __future__ import annotations

from pathlib import Path

from amta.common import workstate
from amta.stores import artifacts
from amta.stores.artifact_store import ArtifactStore
from amta.guards.term_dict import load_master_dict, match_terms

# Default master dict path (relative to project root: data/thbwiki_master_dict.json)
DEFAULT_MASTER_DICT = Path(__file__).parent.parent.parent / "data" / "thbwiki_master_dict.json"


def run_pre_scan(work_id: str, artifacts_dir: Path | str,
                 master_dict_path: Path | str | None = None,
                 _master_dict: dict[str, str] | None = None) -> dict[str, str]:
    """Scan all canon artifacts in artifacts_dir, match terms, write to work_state.

    Args:
        work_id: Work identifier (used for work_state path).
        artifacts_dir: Directory containing page_*_canon.json files.
        master_dict_path: Path to master dict JSON (defaults to project data/).
        _master_dict: INTERNAL — pre-loaded flat dict for testing. Do not use in production.

    Returns:
        {matched_surface: translation} — all terms found in this work.
        Also writes these terms to work_state.terms with status=confirmed, source=pre_scan.
    """
    art_dir = Path(artifacts_dir)

    # Load master dictionary (flat {surface: translation})
    if _master_dict is not None:
        master = _master_dict
    else:
        master = load_master_dict(master_dict_path or DEFAULT_MASTER_DICT)

    if not master:
        return {}

    # Collect all OCR text from all canon artifacts
    all_text_parts: list[str] = []
    skipped_files = 0
    if art_dir.exists():
        store = ArtifactStore(art_dir)
        canon_files = [p for k in store.pages("canon")
                       if (p := store.resolve("canon", k)) is not None]
        for cf in canon_files:
            try:
                doc = artifacts.load_canon(cf)
                for item in doc.get("items", []):
                    txt = item.get("baberu_text") or item.get("text") or ""
                    if txt.strip():
                        all_text_parts.append(txt)
            except Exception:
                skipped_files += 1
                continue

    if skipped_files:
        # Visible degradation signal: silent skipping turns unreadable canon
        # into a fake "no terms found" result (final-review Important #3).
        import sys
        print(f"WARNING: {skipped_files} canon file(s) skipped (unreadable/invalid)",
              file=sys.stderr)

    if not all_text_parts:
        return {}

    combined_text = "\n".join(all_text_parts)

    # Match terms against master dictionary
    matched = match_terms(combined_text, master)

    if not matched:
        return {}

    # Write matched terms to work_state (status=confirmed, source=pre_scan)
    state = workstate.load_state(work_id)
    terms = state.setdefault("terms", {})
    for surface, translation in matched.items():
        # Don't overwrite existing manual terms (manual takes precedence)
        if surface in terms and terms[surface].get("source") == "manual":
            continue
        terms[surface] = {
            "translation": translation,
            "status": "confirmed",
            "source": "pre_scan",
            "master_dict": True,
        }
    workstate.save_state(work_id, state)

    return matched
