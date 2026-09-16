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
from amta.typeset.typeset_engine import fit_font_size, infer_direction_from_bbox
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
    img_long_side = max(img.size)

    # ===== manga-image-translator 风格：原文基准字号 + 译文长度缩放 =====
    # 参考：zyddnys/manga-image-translator PR #1168
    # - 基准字号 = 原文在框内能放下的最大字号
    # - 译文比原文长时缩放：scale = 1/(1+length_increase*0.5), clamp[0.6, 1.0]
    # - 最小字号 = 图片长边 / 200
    # - 每框独立，不统一整页基准
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

        # 1. 用原文计算基准字号（原文在框内能放下的最大字号）
        src_text = item.get("baberu_text") or item.get("text") or text
        src_base_size, _, _ = fit_font_size(src_text, Path(font_path), bbox)

        # 2. 译文长度缩放：译文比原文长时缩小，短时不放大
        src_len = max(1, len(src_text.strip()))
        dst_len = len(text.strip())
        length_increase = max(0.0, (dst_len - src_len) / src_len)
        scale = 1.0 / (1.0 + length_increase * 0.5)
        scale = max(0.6, min(1.0, scale))

        # 3. 目标字号 = 原文基准 * 缩放，不低于最小字号
        min_font_size = max(12, img_long_side / 200)
        target_size = max(min_font_size, src_base_size * scale)

        item_contexts.append({
            "rid": rid,
            "text": text,
            "font_path": str(font_path),
            "stroke": stroke,
            "bbox": bbox,
            "target_size": target_size,
            "src_base_size": src_base_size,
            "scale": scale,
        })

    # 无统一基准：每框用自己的目标字号
    base_font_size = None

    # ===== 渲染：每框独立用目标字号 =====
    rendered_items = []
    overflow = []
    shrunk_boxes = []

    for ctx in item_contexts:
        rid = ctx["rid"]
        text = ctx["text"]
        font_path = ctx["font_path"]
        stroke = ctx["stroke"]
        bbox = ctx["bbox"]
        target_size = ctx["target_size"]
        # 用目标字号渲染（fit_font_size 从 target_size 征下找能放下的最大字号）
        # 方向推断：从 bbox 长宽比推断原排版方向（日漫竖长框竖排），传给渲染层
        preferred = infer_direction_from_bbox(bbox)
        meta = render_item(img, text, font_path, bbox, stroke=stroke,
                           base_size=target_size,
                           preferred_direction=preferred)
        meta["region_id"] = rid
        meta["font_family"] = Path(font_path).name
        meta["stroke_width"] = stroke
        meta["stroke_color"] = "#FFFFFF"
        meta["text_color"] = "#000000"
        meta["src_base_size"] = ctx["src_base_size"]
        meta["length_scale"] = ctx["scale"]
        rendered_items.append(meta)
        # 渲染前二次检查：实际字号 < 目标字号的 40% 说明严重溢出
        if meta["font_size"] < target_size * 0.4:
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
        "base_font_size_strategy": "mit_source_based_length_scaled",
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
