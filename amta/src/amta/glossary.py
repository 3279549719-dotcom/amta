"""Knowledge guardrail（ADR-016）：confirmed 术语译名一致性校验。

对每页：若原文含某 confirmed 术语，译文必须用其 canon 译名或任一 alias；
译文残留该术语日文形式、或用与 canon 不同的中文写法（Levenshtein 相近但不等）→ 违例。
返回违例列表，空=合法。
"""
from __future__ import annotations

from amta.metrics import contains_japanese, levenshtein, norm


def check_glossary(canon: list[dict], translation: dict[str, str], work_state: dict) -> list[str]:
    terms = work_state.get("terms", {})
    violations: list[str] = []
    for r in canon:
        # Front3 双引擎格式（ADR-023）：text 缺失时回退 baberu_text/vlm_text
        src = r.get("text") or r.get("baberu_text") or r.get("vlm_text") or ""
        tgt = (translation.get(r["region_id"]) or "").strip()
        if not tgt:
            continue
        for term, meta in terms.items():
            if meta.get("status") != "confirmed" or not term:
                continue
            if term not in src:
                continue
            canon_zh = (meta.get("translation") or "").strip()
            aliases = [str(a) for a in meta.get("aliases", []) if a]
            # 1) 残留日文形式
            if term in tgt:
                violations.append(f"{r['region_id']}: 术语 {term} 残留日文（应为 {canon_zh}）")
                continue
            if not canon_zh:
                continue
            # 2) 用了与 canon 不同且不在 alias 的中文写法（相近变体）
            if canon_zh in tgt or any(a in tgt for a in aliases):
                continue
            if contains_japanese(tgt):
                continue  # 纯日文残留交给 ②，不重复报
            norm_tgt = norm(tgt)
            norm_canon = norm(canon_zh)
            if norm_canon and levenshtein(norm_tgt[: len(norm_canon)], norm_canon) <= 2 \
                    and norm_canon not in norm_tgt:
                violations.append(f"{r['region_id']}: 术语 {term} 中文写法与 canon {canon_zh} 不一致")
    return violations
