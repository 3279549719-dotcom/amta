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


def union_blocks(detections: dict[str, list[dict]], threshold: float = 0.5) -> list[dict]:
    """多 detector 并集，保留首个命中框的元数据（node_id/bubble_type/ocr 等）。

    union_boxes 只留 bbox；这里把 blocks 的附加字段一并带出，供 01_detect 输出扁平 blocks[]。
    去重判据与 union_boxes 一致（IoU > threshold 视为重复），重复时保留首个出现的完整 block。
    """
    seen: list[dict] = []
    for blocks in detections.values():
        for b in blocks:
            bb = bbox_from_block(b)
            if any(iou(bb, s["bbox"]) > threshold for s in seen):
                continue
            item = dict(b)
            item["bbox"] = bb
            seen.append(item)
    return seen


def _area(bb: Sequence[float]) -> float:
    return max(0.0, bb[2] - bb[0]) * max(0.0, bb[3] - bb[1])


def absorb_contained(blocks: list[dict], ioa_thresh: float = 0.75) -> list[dict]:
    """包含度去重（IoA）：全嵌套于更大框内的碎片子框被吸收丢弃。

    修 L10/并集残留：竖排碎片框（u04「ぽ」在 u05「ぽっらん」内）因 IoU≈0 逃过
    union 去重，此处按 IoA（子框∩容器 / 子框）≥0.75 判定为同一文本区域的碎片，
    丢弃子框，保留更大的容器框。扁平 blocks[] 契约不变（Phase B-light）。
    """
    if not blocks:
        return []
    # 按面积降序：大框先入,后续小框若被某已保留框包含则丢弃
    ordered = sorted(blocks, key=lambda b: _area(b["bbox"]), reverse=True)
    kept: list[dict] = []
    for b in ordered:
        bb = b["bbox"]
        if any(_contained_in(bb, k["bbox"], ioa_thresh) for k in kept):
            continue
        kept.append(b)
    return kept


def _contained_in(child: Sequence[float], parent: Sequence[float], ioa_thresh: float) -> bool:
    """child 是否全嵌套于 parent（IoA ≥ 阈值，即 child 被 parent 覆盖的比例）。"""
    c = _area(child)
    if c <= 0:
        return False
    x0 = max(child[0], parent[0])
    y0 = max(child[1], parent[1])
    x1 = min(child[2], parent[2])
    y1 = min(child[3], parent[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return inter / c >= ioa_thresh
