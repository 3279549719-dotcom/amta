"""共享几何库：bbox 解析、IoU、并集聚合、嵌套标记、category 映射。

唯一归属（/simplify 合并产物）：
- bbox_from_block  ← 合并自 benchmark.py / ocr_detect.py
- iou             ← 合并自 benchmark._iou
- union_boxes     ← 合并自 benchmark.union_boxes
- union_blocks    ← 多 detector 并集，保留元数据（01_detect 输出扁平 blocks[]）
- mark_contained  ← 嵌套框标记（contained_in，不丢弃，留给下游 LLM）
- assign_category ← bubble_type → 3 级 category 映射
"""
from __future__ import annotations

from typing import Sequence


def bbox_from_block(block: dict) -> list[float]:
    """从 block 提取 [x1, y1, x2, y2]（保留 1 位小数）。

    优先使用已算好的 bbox 字段，否则从 koharu 节点 transform 推导。
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

    去重判据与 union_boxes 一致（IoU > threshold 视为重复），重复时保留首个出现的完整 block。
    引擎溯源（ADR-023）：block 已含 source_engines 字段时，新框确保记录当前引擎名，
    重复命中时把当前引擎名追加到已保留框；无该字段的 block 保持旧行为。
    """
    seen: list[dict] = []
    for eng, blocks in detections.items():
        for b in blocks:
            bb = bbox_from_block(b)
            dup = next((s for s in seen if iou(bb, s["bbox"]) > threshold), None)
            if dup is not None:
                src = dup.get("source_engines")
                if isinstance(src, list) and eng not in src:
                    src.append(eng)
                continue
            item = dict(b)
            item["bbox"] = bb
            src = item.get("source_engines")
            if isinstance(src, list):
                item["source_engines"] = list(src)
                if eng not in item["source_engines"]:
                    item["source_engines"].append(eng)
            seen.append(item)
    return seen


def _area(bb: Sequence[float]) -> float:
    return max(0.0, bb[2] - bb[0]) * max(0.0, bb[3] - bb[1])


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


def mark_contained(blocks: list[dict], ioa_threshold: float = 0.75) -> list[dict]:
    """标记嵌套框但不丢弃。

    IoA >= threshold 的小框被标记 contained_in=<父框region_id>，但保留在输出中，
    信息留给下游 LLM 判断。每个框新增 region_id（u00, u01, ...）和 contained_in（None 或父框 id）。
    """
    if not blocks:
        return []

    for i, b in enumerate(blocks):
        b["region_id"] = f"u{i:02d}"
        if "contained_in" not in b:
            b["contained_in"] = None

    sorted_by_area = sorted(blocks, key=lambda b: _area(b["bbox"]), reverse=True)

    for i, small in enumerate(sorted_by_area):
        if small["contained_in"] is not None:
            continue
        for j, big in enumerate(sorted_by_area):
            if i == j:
                continue
            if big["contained_in"] == small["region_id"]:
                continue
            if _contained_in(small["bbox"], big["bbox"], ioa_threshold):
                small["contained_in"] = big["region_id"]
                break

    return blocks


def assign_category(blocks: list[dict]) -> list[dict]:
    """bubble_type 值域统一映射到 3 级 category(Phase 1 / ADR-019)。

    koharu 推断的 bubble_type(dialogue/narration/sfx/unknown/overlay_text)
    → category ∈ {dialogue_bubble, overlay_text, sfx}。
    映射规则: dialogue/narration/unknown → dialogue_bubble; sfx → sfx; overlay_text 透传。
    保留原 bubble_type 字段(兼容下游)。
    """
    _MAP = {
        "dialogue": "dialogue_bubble",
        "narration": "dialogue_bubble",
        "unknown": "dialogue_bubble",
        "sfx": "sfx",
        "overlay_text": "overlay_text",
    }
    out = []
    for b in blocks:
        item = dict(b)
        bt = item.get("bubble_type")
        item["category"] = _MAP.get(bt if isinstance(bt, str) else "",
                                     "dialogue_bubble")
        out.append(item)
    return out
