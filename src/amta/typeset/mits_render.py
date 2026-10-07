"""MITS（manga-image-translator-style）普通路径渲染。

从 typeset_station.py 拆出：逐框按原文基准字号 fit_font_size，再对译文做实际适配。
不使用 VLM layout observation。
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from amta.common.paths import read_json, write_json
from amta.stores.artifacts import load_canon
from amta.typeset.fonts import resolve_font
from amta.typeset.typeset_engine import fit_font_size, infer_direction_from_bbox
from amta.typeset.typeset_render import _normalize_text_for_render, render_item


def render_page(work_id: str, canon_path: Path, trans_path: Path, det_path: Path,
                clean_path: Path, out_path: Path, final_path: Path) -> dict:
    """普通页排版：clean 图 + canon + translation + detection → final.png + typeset.json。"""
    canon_doc = load_canon(canon_path)
    canon_items = canon_doc["items"]
    trans = read_json(trans_path).get("translations", {}) or {}
    det = read_json(det_path)

    bbox_by_rid = {}
    for b in (det.get("blocks") or []):
        rid = b.get("region_id")
        if rid:
            bbox_by_rid[rid] = b.get("bbox")

    img = Image.open(clean_path).convert("RGB")
    img_long_side = max(img.size)

    # 逐框目标字号：原文在框内能放下的最大字号
    canon_ids = {c.get("region_id") for c in canon_items}
    item_contexts = []
    skipped_no_bbox = []

    for item in canon_items:
        rid = item.get("region_id")
        text = trans.get(rid)
        if text is None:
            continue
        bbox = bbox_by_rid.get(item.get("region_id"))
        if not bbox:
            skipped_no_bbox.append(rid)
            continue
        category = item.get("category")
        font_path, stroke = resolve_font(category or "dialogue_bubble", text)

        # 原文基准字号：必须先做与渲染同一步的字符规范化（render_item 内部会跑
        # _normalize_text_for_render），否则同一句话在「算基准字号」和「实际渲染」
        # 两步得到不同的字符数/度量——例如 "こいつ...!!" 的三个 ASCII 点会被渲染层
        # 归一成一个省略号，基准字号却按三个点算，直接把整格字号压小一档
        # （2026-10-07 タガタメ 0030 r08 事故）。
        src_text = item.get("baberu_text") or item.get("text") or text
        src_base_size, _, _ = fit_font_size(
            _normalize_text_for_render(src_text), Path(font_path), bbox
        )
        target_size = max(max(12, img_long_side / 200), src_base_size)

        item_contexts.append({
            "rid": rid, "text": text, "font_path": str(font_path), "stroke": stroke,
            "bbox": bbox, "target_size": target_size, "src_base_size": src_base_size,
        })

    rendered_items = []
    overflow = []
    shrunk_boxes = []

    for ctx in item_contexts:
        rid = ctx["rid"]
        preferred = infer_direction_from_bbox(ctx["bbox"])
        meta = render_item(img, ctx["text"], ctx["font_path"], ctx["bbox"],
                           stroke=ctx["stroke"], base_size=ctx["target_size"],
                           preferred_direction=preferred)
        meta["region_id"] = rid
        meta["font_family"] = Path(ctx["font_path"]).name
        meta["stroke_width"] = ctx["stroke"]
        meta["stroke_color"] = "#FFFFFF"
        meta["text_color"] = "#000000"
        meta["src_base_size"] = ctx["src_base_size"]
        rendered_items.append(meta)
        if meta["font_size"] < ctx["target_size"] * 0.4:
            overflow.append(rid)

    if final_path:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(final_path)

    translated = [rid for rid in trans if rid in canon_ids]
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

    page_key = det.get("page", out_path.stem.removesuffix("_typeset"))
    doc = {
        "work_id": work_id,
        "page": det.get("page", ""),
        "renderer": "mits-source-fit",
        "rendered_items": rendered_items,
        "layout": layout,
        "final_image": f"final/{page_key}_final.png" if final_path else "",
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
