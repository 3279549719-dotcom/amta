"""pre-translate Input schema 校验（机械硬约束，ADR-016）。

canon_text.json 结构: [{region_id, text, page}]。校验 region_id 唯一非空、
text 非空、page 为 int。返回问题列表，空=合法。
"""
from __future__ import annotations

from typing import Any


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
        if not str(r.get("text") or "").strip():
            problems.append(f"item {i}: empty text")
        if not isinstance(r.get("page"), int):
            problems.append(f"item {i}: bad page")
    return problems
