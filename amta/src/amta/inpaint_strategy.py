"""Stage 4 擦除策略(纯函数,零依赖): bubble_type → fill_white / inpaint / skip。

text_bubble 白底直填(气泡本来就是白的);
text_free 走 mask+inpaint(文字在画面背景上,需要修复背景);
bbox 越界/缺失防御性 skip。

兼容旧字段 category(dialogue_bubble/overlay_text/sfx),新字段 bubble_type(text_bubble/text_free)。
"""
from __future__ import annotations

FILL_WHITE = "fill_white"
INPAINT = "inpaint"
SKIP = "skip"


def _resolve_category(r: dict) -> str:
    """从 region 解析分类: 优先 bubble_type(新), 兼容 category(旧)。"""
    bt = r.get("bubble_type")
    if bt:
        return "dialogue_bubble" if bt == "text_bubble" else "overlay_text"
    return r.get("category") or "dialogue_bubble"  # 保守默认涂白


def plan_inpaint(regions: list[dict], image_meta: dict | None = None) -> list[dict]:
    plan = []
    for r in regions:
        cat = _resolve_category(r)
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
