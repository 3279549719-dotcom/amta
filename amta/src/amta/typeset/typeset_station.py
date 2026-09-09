"""typeset 工位库函数 — clean 图 + canon + translation + detection → final.png + typeset 产物(Stage 5)。

从 scripts/05_typeset.py 抽取，canon 用 load_canon 规范化（兼容信封格式）。
bbox 关联: canon.node_id → detection.blocks[].node_id（零契约改动，ADR-019 不变）。
ADR-031 决策C：删除 decide_direction，方向由 fit_font_size 双方向选优自动决定。
气泡框收缩：ADR-031 后对所有框排版前调用 shrink_bubble_bbox，detect框比文字大时自动收缩到实际边界。
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from amta.stores.artifacts import load_canon
from amta.typeset.fonts import resolve_font
from amta.common.geometry import shrink_bubble_bbox
from amta.common.paths import read_json, write_json
from amta.typeset.typeset_render import render_item


def run(work_id: str, canon_path: Path, trans_path: Path, det_path: Path,
        clean_path: Path, out_path: Path, final_path: Path) -> dict:
    """单页排版：clean 图 + canon + translation + detection → final.png + typeset.json。"""
    canon_doc = load_canon(canon_path)
    canon_items = canon_doc["items"]
    trans = read_json(trans_path).get("translations") or {}
    det = read_json(det_path)
    # 存 bbox，供排版前收缩用（ADR-031: 对所有框收缩，不再区分 bubble_type）
    bbox_by_rid = {}
    for b in (det.get("blocks") or []):
        rid = b.get("region_id")
        if rid:
            bbox_by_rid[rid] = b.get("bbox")

    img = Image.open(clean_path).convert("RGB")
    rendered_items = []
    skipped_no_bbox = []
    overflow = []
    shrunk_boxes = []
    canon_ids = {c.get("region_id") for c in canon_items}

    for item in canon_items:
        rid = item.get("region_id")
        text = trans.get(rid)
        if text is None:
            continue
        bbox = bbox_by_rid.get(item.get("region_id"))
        if not bbox:
            skipped_no_bbox.append(rid)
            continue
        # ADR-031: 对所有框排版前收缩到实际边界（detect框比文字大时不出框）
        original_bbox = list(bbox)
        bbox = shrink_bubble_bbox(img, bbox)
        if bbox != original_bbox:
            shrunk_boxes.append(rid)
        category = item.get("category")
        font_path, stroke = resolve_font(category or "dialogue_bubble", text)
        meta = render_item(img, text, str(font_path), bbox, stroke=stroke)
        meta["region_id"] = rid
        meta["font_family"] = font_path.name
        meta["stroke_width"] = stroke
        meta["stroke_color"] = "#FFFFFF"
        meta["text_color"] = "#000000"
        rendered_items.append(meta)
        if meta["font_size"] <= 12 and len("".join(meta.get("lines") or [])) < len(text):
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
