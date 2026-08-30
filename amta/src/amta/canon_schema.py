"""pre-translate Input schema 校验（机械硬约束，ADR-016）。

canon_text.json 结构: [{region_id, text, page}] 或 Front3 双引擎格式
[{region_id, baberu_text, vlm_text, page}]（ADR-023）。校验 region_id 唯一非空、
文本非空（text 或 baberu_text/vlm_text 至少一个）、page 为 int。返回问题列表，空=合法。
"""
from __future__ import annotations

from typing import Any

CATEGORIES = {"dialogue_bubble", "overlay_text", "sfx"}
SUB_TIERS = {"primary", "aside"}


def validate_canon(canon: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(canon, list):
        return ["canon must be a list"]
    seen: set[str] = set()
    for i, r in enumerate(canon):
        if not isinstance(r, dict):
            problems.append(f"item {i} must be dict")
            continue
        rid = r.get("region_id")
        if not rid or not str(rid).strip():
            problems.append(f"item {i}: missing region_id")
        elif rid in seen:
            problems.append(f"duplicate region_id {rid}")
        else:
            seen.add(rid)
        # Front3 双引擎格式（ADR-023）：text 或 baberu_text/vlm_text 至少一个非空
        texts = [r.get("text"), r.get("baberu_text"), r.get("vlm_text")]
        if not any(str(t or "").strip() for t in texts):
            problems.append(f"item {i}: empty text")
        if not isinstance(r.get("page"), int):
            problems.append(f"item {i}: bad page")
        cat = r.get("category")
        if cat is not None and cat not in CATEGORIES:
            problems.append(f"item {i}: bad category {cat!r}")
        st = r.get("sub_tier")
        if st is not None and st not in SUB_TIERS:
            problems.append(f"item {i}: bad sub_tier {st!r}")
    return problems
