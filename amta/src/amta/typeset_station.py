"""typeset 工位库函数 — clean 图 + canon + translation + detection → final.png + typeset 产物(Stage 5)。

从 scripts/05_typeset.py 抽取，逻辑不变。
bbox 关联: canon.node_id → detection.blocks[].node_id（零契约改动，ADR-019 不变）。
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from amta.fonts import resolve_font
from amta.paths import read_json, write_json
from amta.typeset_engine import decide_direction
from amta.typeset_render import render_item


def run(work_id: str, canon_path: Path, trans_path: Path, det_path: Path,
        clean_path: Path, out_path: Path, final_path: Path) -> dict:
    """单页排版：clean 图 + canon + translation + detection → final.png + typeset.json。

    Args:
        work_id: 工作区 ID
        canon_path: canon.json 路径（来自 ocr）
        trans_path: translation.json 路径（来自 translate）
        det_path: detection.json 路径（来自 detect，用于 node_id→bbox 映射）
        clean_path: clean.png 路径（来自 inpaint）
        out_path: typeset.json 输出路径
        final_path: final.png 输出路径
    """
    canon = read_json(canon_path)
    trans = read_json(trans_path).get("translations") or {}
    det = read_json(det_path)
    bbox_by_node = {b.get("node_id"): b.get("bbox")
                    for b in (det.get("blocks") or []) if b.get("node_id")}

    img = Image.open(clean_path).convert("RGB")
    rendered_items = []
    skipped_no_bbox = []
    overflow = []
    canon_ids = {c.get("region_id") for c in canon}

    for item in canon:
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
