"""共享几何库：bbox 解析、IoU、并集聚合（纯数值原语）。

区域契约语义（build_regions/flatten_regions/mark_contained/assign_*）的
唯一归属已迁至 `amta.regions`（refactor/modular-architecture，L28），
本文件保留兼容 re-export，新代码请直接 import amta.regions。

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
    引擎溯源（ADR-023）：遍历 detections.items()，block 已含 source_engines 字段时，
    新框确保记录当前引擎名，重复命中时把当前引擎名追加到已保留框（去重、顺序稳定）；
    无该字段的 block 保持旧行为（不新增字段）。
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
                item["source_engines"] = list(src)  # 拷贝，避免与调用方共享可变列表
                if eng not in item["source_engines"]:
                    item["source_engines"].append(eng)
            seen.append(item)
    return seen


# ---- 兼容层：区域契约已迁至 amta.regions（唯一归属），旧 import 路径继续可用 ----
from amta.regions import (  # noqa: E402, F401  # 兼容 re-export，勿在此模块新增实现
    absorb_contained,
    assign_category,
    assign_sub_tier,
    build_regions,
    flatten_regions,
    mark_contained,
)
