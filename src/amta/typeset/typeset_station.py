"""typeset 工位库函数 — clean 图 + canon + translation + detection → final.png + typeset 产物(Stage 5)。

从 scripts/05_typeset.py 抽取，canon 用 load_canon 规范化（兼容信封格式）。
bbox 关联: canon.node_id → detection.blocks[].node_id（零契约改动，ADR-019 不变）。
ADR-033 决策C：删除 decide_direction，方向由 fit_font_size 双方向选优自动决定。
气泡框收缩：ADR-033 后对所有框排版前调用 shrink_bubble_bbox，detect框比文字大时自动收缩到实际边界。

2026-09-11 自适应基准字号（v3）：
- 不硬编码任何阈值（不用图片长边/90，不用50%/70%相对下限）。
- 两遍算法：第一遍计算每个框能放下的最大字号 → 取最小值作为整页基准 → 第二遍所有框统一用基准字号渲染。
- 结果：所有字大小完全一致，都能放进框里，不会溢出，完全自适应。
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from amta.common.paths import read_json, write_json
from amta.stores.artifacts import load_canon
from amta.typeset.fonts import resolve_font
from amta.typeset.typeset_engine import fit_font_size
from amta.typeset.typeset_render import render_item


def run(work_id: str, canon_path: Path, trans_path: Path, det_path: Path,
        clean_path: Path, out_path: Path, final_path: Path) -> dict:
    """单页排版：clean 图 + canon + translation + detection → final.png + typeset.json。

    自适应基准字号算法（两遍）：
    1. 第一遍：对每个框计算能放下的最大字号（不渲染）
    2. 取所有框的最小值作为整页基准字号
    3. 第二遍：所有框统一用基准字号渲染
    """
    canon_doc = load_canon(canon_path)
    canon_items = canon_doc["items"]
    trans = read_json(trans_path).get("translations") or {}
    det = read_json(det_path)
    # 存 bbox，供排版前收缩用（ADR-033: 对所有框收缩，不再区分 bubble_type）
    bbox_by_rid = {}
    for b in (det.get("blocks") or []):
        rid = b.get("region_id")
        if rid:
            bbox_by_rid[rid] = b.get("bbox")

    img = Image.open(clean_path).convert("RGB")

    # ===== 第一遍：计算每个框能放下的最大字号（不渲染） =====
    canon_ids = {c.get("region_id") for c in canon_items}
    item_contexts = []  # 存储每个item的上下文（text, font_path, stroke, bbox），供第二遍使用
    max_sizes = []  # 每个框能放下的最大字号
    skipped_no_bbox = []  # 找不到bbox的item（第一遍就记录，避免丢失）

    for item in canon_items:
        rid = item.get("region_id")
        text = trans.get(rid)
        if text is None:
            continue
        bbox = bbox_by_rid.get(item.get("region_id"))
        if not bbox:
            skipped_no_bbox.append(rid)
            continue
        # ADR-033: 对所有框排版前收缩到实际边界
        # 2026-09-11 禁用：shrink_bubble_bbox 在黑色背景框上过度收缩
        # （如 P18 r08 91x221 -> 10x17），导致整页基准字号被拉低到12px
        # bbox = shrink_bubble_bbox(img, bbox)
        category = item.get("category")
        font_path, stroke = resolve_font(category or "dialogue_bubble", text)
        # 计算这个框能放下的最大字号（不用base_size，从MAX_SIZE往下找）
        max_size, _, _ = fit_font_size(text, Path(font_path), bbox)
        max_sizes.append(max_size)
        item_contexts.append({
            "rid": rid,
            "text": text,
            "font_path": str(font_path),
            "stroke": stroke,
            "bbox": bbox,
        })

    # 取所有框的最小值作为整页基准字号（自适应，不硬编码）
    if max_sizes:
        base_font_size = min(max_sizes)
    else:
        base_font_size = 24  # 兜底：没有任何框时用默认值

    # ===== 第二遍：所有框统一用基准字号渲染 =====
    rendered_items = []
    overflow = []
    shrunk_boxes = []

    for ctx in item_contexts:
        rid = ctx["rid"]
        text = ctx["text"]
        font_path = ctx["font_path"]
        stroke = ctx["stroke"]
        bbox = ctx["bbox"]
        # 用基准字号渲染（base_size=base_font_size，所有框统一字号）
        meta = render_item(img, text, font_path, bbox, stroke=stroke,
                           base_size=base_font_size)
        meta["region_id"] = rid
        meta["font_family"] = Path(font_path).name
        meta["stroke_width"] = stroke
        meta["stroke_color"] = "#FFFFFF"
        meta["text_color"] = "#000000"
        rendered_items.append(meta)
        # overflow 检测：字号等于基准字号但内容放不下（理论上不应该发生，因为基准是最小值）
        if meta["font_size"] < base_font_size and len("".join(meta.get("lines") or [])) < len(text):
            overflow.append(rid)

    if final_path:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(final_path)

    translated = [rid for rid in trans if rid in canon_ids]
    # layout 字典（按 region_id 索引，供报告模块消费）
    layout = {}
    for item in rendered_items:
        rid = item.get("region_id", "")
        if rid:
            layout[rid] = {
                "layout_direction": item.get("layout_direction", ""),
                "font_size": item.get("font_size", 0),
                "lines": item.get("lines", []),
                "anchor_pos": item.get("anchor_pos", []),
            }
    page_key = det.get("page", out_path.stem.removesuffix("_typeset")); final_image_rel = f"final/{page_key}_final.png" if final_path else ""
    doc = {
        "work_id": work_id,
        "page": det.get("page", ""),
        "base_font_size": base_font_size,
        "base_font_size_strategy": "adaptive_min_of_max_per_box",
        "rendered_items": rendered_items,
        "layout": layout,
        "final_image": final_image_rel,
        "checks": {
            "rendered": len(rendered_items),
            "translated": len(translated),
            "coverage_complete": len(rendered_items) == len(translated),
            "overflow": overflow,
            "skipped_no_bbox": skipped_no_bbox,
            "shrunk_bubbles": shrunk_boxes,
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(out_path, doc)
    return doc
