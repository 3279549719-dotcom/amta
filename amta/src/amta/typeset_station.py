"""typeset 工位库函数 — clean 图 + canon + translation + detection → final.png + typeset 产物(Stage 5)。

从 scripts/05_typeset.py 抽取，canon 用 load_canon 规范化（兼容信封格式）。
bbox 关联: canon.node_id → detection.blocks[].node_id（零契约改动，ADR-019 不变）。
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from amta.artifacts import load_canon
from amta.fonts import resolve_font
from amta.paths import read_json, write_json
from amta.typeset_engine import decide_direction
from amta.typeset_render import render_item


def run(work_id: str, canon_path: Path, trans_path: Path, det_path: Path,
        clean_path: Path, out_path: Path, final_path: Path) -> dict:
    """单页排版：clean 图 + canon + translation + detection → final.png + typeset.json。"""
    canon_doc = load_canon(canon_path)
    canon_items = canon_doc["items"]
    trans = read_json(trans_path).get("translations") or {}
    det = read_json(det_path)
    bbox_by_node = {b.get("node_id"): b.get("bbox")
                    for b in (det.get("blocks") or []) if b.get("node_id")}

    img = Image.open(clean_path).convert("RGB")
    rendered_items = []
    skipped_no_bbox = []
    overflow = []
    canon_ids = {c.get("region_id") for c in canon_items}

    for item in canon_items:
        rid = item.get("region_id")
        text = trans.get(rid)
        if text is None:
            continue
        bbox = bbox_by_node.get(item.get("node_id"))
        if not bbox:
            skipped_no_bbox.append(rid)
            continue
        category = item.get("category")
        font_path, stroke = resolve_font(category or "dialogue_bubble", text)
        direction = decide_direction(category, bbox, len(text))
        meta = render_item(img, text, str(font_path), bbox, direction, stroke=stroke)
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
    doc = {
        "work_id": work_id,
        "page": det.get("page", ""),
        "rendered_items": rendered_items,
        "checks": {
            "rendered": len(rendered_items),
            "translated": len(translated),
            "coverage_complete": len(rendered_items) == len(translated),
            "overflow": overflow,
            "skipped_no_bbox": skipped_no_bbox,
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(out_path, doc)
    return doc
