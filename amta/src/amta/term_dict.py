"""Term dictionary: load THBWiki master dictionary and match terms in text.

Master dict is structured JSON (characters + lore_terms + honorific_map).
Loader flattens it to {surface_form: chinese_translation}.
Matcher does exact → normalized → fuzzy (levenshtein ≤ 2, ≤ 1 for 3-char terms) matching.
"""
from __future__ import annotations

import json
from pathlib import Path

from amta.metrics import levenshtein, norm


def load_master_dict(path: Path | str) -> dict[str, str]:
    """Load structured master dict JSON and flatten to {surface: translation}.

    Expands character aliases (each alias has explicit surface+translation).
    Lore terms are added directly. honorific_map is metadata only (not in flat map).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Master dictionary not found: {p}")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)

    flat: dict[str, str] = {}
    for char in data.get("characters", []):
        surface = char["surface"]
        translation = char["translation"]
        flat[surface] = translation
        for alias in char.get("aliases", []):
            flat[alias["surface"]] = alias["translation"]
    for lore in data.get("lore_terms", []):
        flat[lore["surface"]] = lore["translation"]
    return flat


def match_terms(text: str, term_map: dict[str, str]) -> dict[str, str]:
    """Find which terms from term_map appear in text.

    Matching strategy (in order, first hit wins per term):
      1. Exact substring match
      2. Normalized match (norm() strips punctuation/whitespace)
      3. Fuzzy match: sliding window of len(term)±0, levenshtein ≤ 2 (≤ 1 for 3-char terms)

    Terms are processed longest-first to avoid partial overlaps.
    Returns {matched_surface: translation} (only terms that were found).
    """
    if not text or not term_map:
        return {}

    norm_text = norm(text)
    matched: dict[str, str] = {}

    # Longest-first so サグ姉 matches before サグメ (no partial overlap)
    for term in sorted(term_map.keys(), key=len, reverse=True):
        translation = term_map[term]
        norm_term = norm(term)
        if not norm_term:
            continue

        # 1. Exact match
        if term in text:
            matched[term] = translation
            continue

        # 2. Normalized match (handles 「」、spaces, etc.)
        if norm_term in norm_text:
            matched[term] = translation
            continue

        # 3. Fuzzy match for OCR errors (levenshtein ≤ 2)
        #    Only for terms ≥ 3 chars; slide a window over normalized text
        if len(norm_term) >= 3:
            found = False
            tlen = len(norm_term)
            # Distance budget scales with length: a 3-char window at
            # distance 2 aligns only 1/3 chars (matches common grammar
            # like ている), so 3-char terms allow at most 1 edit.
            max_dist = 2 if len(norm_term) >= 4 else 1
            for i in range(max(0, len(norm_text) - tlen + 1)):
                window = norm_text[i:i + tlen]
                if len(window) == tlen and levenshtein(window, norm_term) <= max_dist:
                    matched[term] = translation
                    found = True
                    break
            if found:
                continue

    return matched
