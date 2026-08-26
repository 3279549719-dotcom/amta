"""共享几何库：bbox 解析、IoU、并集聚合。

唯一归属（/simplify 合并产物）：
- bbox_from_block  ← 合并自 benchmark.py / ocr_detect.py / recall_detect.py
- iou             ← 合并自 benchmark._iou / recall_crop.iou
- union_boxes     ← 合并自 benchmark.union_boxes
"""
from __future__ import annotations

from typing import Sequence


def bbox_from_block(block: dict) -> list[float]:
    """从 block 提取 [x1, y1, x2, y2]（保留 1 位小数）。

    优先使用已算好的 bbox 字段（recall_detect/ocr_detect 的 compact 输出），
    否则从 koharu 节点 transform 推导。
    """
    bb = block.get("bbox")
    if isinstance(bb, (list, tuple)) and len(bb) == 4:
        return [round(float(v), 1) for v in bb]
    t = block.get("transform", {})
    x = float(t.get("x", 0))
    y = float(t.get("y", 0))
    w = float(t.get("w", t.get("width", 0)))
    h = float(t.get("h", t.get("height", 0)))
    return [round(x, 1), round(y, 1), round(x + w, 1), round(y + h, 1)]


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    """两个 [x1,y1,x2,y2] 框的 IoU。"""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua > 0 else 0.0


def union_boxes(detections: dict[str, list[dict]], threshold: float = 0.5) -> list[dict]:
    """多 detector 并集：仅保留唯一 bbox（IoU > threshold 视为重复）。"""
    seen: list[tuple[float, ...]] = []
    for blocks in detections.values():
        for b in blocks:
            bb = tuple(bbox_from_block(b))
            if any(iou(bb, s) > threshold for s in seen):
                continue
            seen.append(bb)
    return [{"bbox": list(s)} for s in seen]
