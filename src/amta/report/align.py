"""跨阶段区域对齐 — 优先 region_id 精确匹配，回退 bbox IoU 物理匹配。

IoU 逻辑复用 05b6e99 已验证的 gen_visual_report.py 实现。
"""
from __future__ import annotations


def iou(b1: list[float], b2: list[float]) -> float:
    """两个 bbox [x1,y1,x2,y2] 的交并比。"""
    x1, y1, x2, y2 = b1
    a1, c1, a2, c2 = b2
    ix1, iy1 = max(x1, a1), max(y1, c1)
    ix2, iy2 = min(x2, a2), min(y2, c2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    area1 = (x2 - x1) * (y2 - y1)
    area2 = (a2 - a1) * (c2 - c1)
    union = area1 + area2 - inter
    return inter / union if union > 0 else 0.0


def match_region(
    target_rid: str,
    target_bbox: list[float] | None,
    candidate_ids: list[str],
    candidate_bboxes: dict[str, list[float]],
    thr: float = 0.5,
) -> str | None:
    """在候选区域里找与 target 同一物理框的 region_id。

    优先精确匹配 region_id；匹配不上且有 bbox 时用 IoU > thr 找物理框。
    """
    if target_rid in candidate_ids:
        return target_rid
    if target_bbox is None:
        return None
    best, best_iou = None, 0.0
    for cid in candidate_ids:
        cb = candidate_bboxes.get(cid)
        if cb is None:
            continue
        v = iou(target_bbox, cb)
        if v > best_iou:
            best, best_iou = cid, v
    return best if best_iou > thr else None
