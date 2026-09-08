"""Stage 4 擦除策略(纯函数,零依赖): 所有框统一走 mask+inpaint(本地 lama-manga)。

ADR-030: 移除 text_bubble 白底直填分支。
- 原策略: text_bubble → fill_white / text_free → inpaint
- 假设: 气泡一定是白底
- 反例: 黑底白字、气泡内网点、灰底气泡 → 涂白产生白色方块盖背景
- 新策略: 所有框统一走 lama inpaint,由模型根据周围像素推断背景
- bbox 越界/缺失防御性 skip。

兼容旧字段 category(dialogue_bubble/overlay_text/sfx),新字段 bubble_type(text_bubble/text_free)。
category 仅用于日志记录,不再影响 action 决策。
"""
from __future__ import annotations

FILL_WHITE = "fill_white"  # 保留常量向后兼容,ADR-030 后不再使用
INPAINT = "inpaint"
SKIP = "skip"


def _resolve_category(r: dict) -> str:
    """从 region 解析分类: 优先 bubble_type(新), 兼容 category(旧)。"""
    bt = r.get("bubble_type")
    if bt:
        return "dialogue_bubble" if bt == "text_bubble" else "overlay_text"
    return r.get("category") or "dialogue_bubble"


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
        # ADR-030: 所有框统一走 inpaint,不再区分 text_bubble/text_free
        action = INPAINT
        plan.append({"region_id": r.get("region_id"), "category": cat,
                     "action": action, "bbox": bb})
    return plan
