"""Stage 4 擦除策略(纯函数,零依赖): category → fill_white / inpaint / skip。

ADR-019 + Spec §2: dialogue_bubble 白底直填(蓝图 bypass invariant);
overlay_text / sfx 走 mask+inpaint;bbox 越界/缺失防御性 skip。
sfx_triage(旁注/保全)延后——本期 sfx 一律 inpaint。
"""
from __future__ import annotations

FILL_WHITE = "fill_white"
INPAINT = "inpaint"
SKIP = "skip"


def plan_inpaint(regions: list[dict], image_meta: dict | None = None) -> list[dict]:
    plan = []
    for r in regions:
        cat = r.get("category") or "dialogue_bubble"  # 兼容旧产物,保守默认
        bb = r.get("bbox")
        if not bb or len(bb) != 4:
            plan.append({"region_id": r.get("region_id"), "category": cat,
                         "action": SKIP, "bbox": bb, "reason": "no bbox"})
            continue
        if image_meta:
            w, h = image_meta.get("width", 1e9), image_meta.get("height", 1e9)
            x1, y1, x2, y2 = bb
            if x1 < 0 or y1 < 0 or x2 > w or y2 > h:
                plan.append({"region_id": r.get("region_id"), "category": cat,
                             "action": SKIP, "bbox": bb,
                             "reason": "bbox out of bounds"})
                continue
        action = FILL_WHITE if cat == "dialogue_bubble" else INPAINT
        plan.append({"region_id": r.get("region_id"), "category": cat,
                     "action": action, "bbox": bb})
    return plan
