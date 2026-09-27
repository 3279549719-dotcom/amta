"""擦除路由：气泡内字收缩涂白，框外字及未知类别保留背景分流。

优先使用显式 category；正式检测产物以 det_label=1/2 表示框内/框外字。
不恢复已移除的 bubble_type 字段。空译文由调用方过滤。
"""
from __future__ import annotations

FILL_WHITE = "fill_white"
INPAINT = "inpaint"
SKIP = "skip"




def plan_inpaint(regions: list[dict], image_meta: dict | None = None) -> list[dict]:
    plan = []
    for r in regions:
        bb = r.get("bbox")
        if not bb or len(bb) != 4:
            plan.append({"region_id": r.get("region_id"), "category": r.get("category", "dialogue_bubble"),
                         "action": SKIP, "bbox": bb, "reason": "no bbox"})
            continue
        if image_meta:
            w, h = image_meta.get("width", 1e9), image_meta.get("height", 1e9)
            x1, y1, x2, y2 = bb
            if x1 < 0 or y1 < 0 or x2 > w or y2 > h:
                plan.append({"region_id": r.get("region_id"), "category": r.get("category", "dialogue_bubble"),
                             "action": SKIP, "bbox": bb,
                             "reason": "bbox out of bounds"})
                continue
        category = r.get("category")
        is_bubble = category == "dialogue_bubble" if category else r.get("det_label") == 1
        action = FILL_WHITE if is_bubble else INPAINT
        plan.append({"region_id": r.get("region_id"), "category": r.get("category", "dialogue_bubble"),
                     "action": action, "bbox": bb})
    return plan
