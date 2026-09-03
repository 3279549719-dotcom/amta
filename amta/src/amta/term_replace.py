"""Direct term replacement: replace locked terms in source text with Chinese translations.

This is the core mechanical guardrail. Before sending text to the LLM,
all locked terminology (from pre-scan) is directly replaced in the source.
The LLM then translates a 日中混合文 — Chinese terms are already correct,
LLM only translates remaining Japanese. No retry, no repair, one pass.

Replacement is longest-match-first to avoid partial overlaps
(e.g., サグ姉 replaced before サグメ can partially match inside it).
"""
from __future__ import annotations


def replace_terms(text: str, term_map: dict[str, str]) -> str:
    """Replace all occurrences of terms in term_map with their translations.

    Args:
        text: Source Japanese text (may contain terms to replace).
        term_map: {surface_form: chinese_translation} — only locked terms.

    Returns:
        Text with terms replaced. Already-Chinese text is not re-matched
        because we do a single pass (not recursive).
    """
    if not text or not term_map:
        return text

    result = text
    # Longest-first: replace サグ姉 before サグメ so shorter term doesn't
    # partially match inside a longer one that's already been replaced.
    for term in sorted(term_map.keys(), key=len, reverse=True):
        translation = term_map[term]
        if term and term in result:
            result = result.replace(term, translation)
    return result


def replace_in_canon(canon_items: list[dict], term_map: dict[str, str]) -> list[dict]:
    """Replace terms in baberu_text of each canon region. Returns a new list.

    For each region, reads baberu_text (falls back to text), applies replace_terms,
    and writes result back to baberu_text. Original list is not mutated.

    Args:
        canon_items: List of region dicts (each with region_id, baberu_text, page, etc.).
        term_map: {surface_form: chinese_translation} — locked terms from pre-scan.

    Returns:
        New list of region dicts with baberu_text replaced.
    """
    if not canon_items or not term_map:
        # Return shallow copies to avoid mutating input even when no replacement
        return [dict(r) for r in canon_items]

    result = []
    for r in canon_items:
        item = dict(r)  # shallow copy — don't mutate original
        src = item.get("baberu_text") or item.get("text") or ""
        if src:
            item["baberu_text"] = replace_terms(src, term_map)
        result.append(item)
    return result
