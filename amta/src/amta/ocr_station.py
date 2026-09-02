"""Stage 2 OCR 工位 — detection + raw 页 → CanonArtifact（深模块）。

最终选型: baberu-OCR（主引擎） + VLM contact sheet 批量校验（质检） + 规则过滤（假框过滤）。
流程: 裁框 → baberu OCR → 规则过滤(pure_punct/pure_number/extreme_aspect/edge_box) → VLM 校验 → canon。
藏匿：裁框（region_id 与 detect 输出顺序一一对应）、baberu 批量 OCR、规则过滤、
VLM contact sheet 校验、VLM key 解析（amta.config）、双引擎输出（baberu_text + vlm_text）、
trace、save_canon（doc 化）。
接缝：ocr_fn / vlm_fn 函数注入（内部接缝，测试用 fake）。
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from amta import artifacts
from amta.config import get_vlm_api_key
from amta.paths import write_json
from amta.rule_filter import rule_filter


def _crop_by_region(raw_page: Path, blocks: list[dict], page_idx: int,
                    crop_dir: Path) -> list[tuple[str, dict, Path, Image.Image]]:
    """按 bbox 裁框；region_id 与 detect 输出顺序一一对应（单空间）。"""
    img = Image.open(raw_page)
    out = []
    crop_dir.mkdir(parents=True, exist_ok=True)
    for i, b in enumerate(blocks):
        bb = b.get("bbox")
        if not bb or len(bb) != 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bb]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img.width, x2), min(img.height, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        rid = b.get("region_id") or artifacts.region_id(page_idx, i)
        crop = crop_dir / f"{rid}.png"
        pil_crop = img.crop((x1, y1, x2, y2))
        pil_crop.save(crop)
        out.append((rid, b, crop, pil_crop))
    return out


def ocr_page(work_id: str, det: dict, raw_page: Path, artifacts_dir: Path, *,
             page_idx: int, vlm_enabled: bool = True,
             ocr_fn=None, vlm_fn=None, vlm_api_key: str | None = None,
             crop_dir: Path | str | None = None) -> dict:
    """单页 OCR：裁框 → baberu → 规则过滤 → VLM 校验 → CanonArtifact（doc 信封）。"""
    from amta.ocr_engines import ocr_batch as _default_ocr
    from amta.vlm_verify import vlm_verify_batch as _default_vlm
    ocr_fn = ocr_fn or _default_ocr
    vlm_fn = vlm_fn or _default_vlm
    page = artifacts.page_key(page_idx)
    artifacts_dir = Path(artifacts_dir)

    blocks = det.get("blocks", [])
    crop_dir = Path(crop_dir) if crop_dir else artifacts_dir / "crops"
    pairs = _crop_by_region(raw_page, blocks, page_idx, crop_dir)
    if not pairs:
        raise RuntimeError(f"02_ocr: no valid bbox on {page} (source {det.get('page', '?')})")

    # ---- baberu OCR ----
    t0 = time.time()
    ocr_rows = ocr_fn([str(c) for _, _, c, _ in pairs])
    ocr_by_crop = {r["crop"]: (r.get("ocr") or "").strip() for r in ocr_rows}
    baberu_elapsed = time.time() - t0

    # ---- 规则过滤（假框过滤）----
    img_w, img_h = Image.open(raw_page).size
    ocr_blocks = []
    for rid, b, crop, _pil in pairs:
        ob = dict(b)
        ob["region_id"] = rid
        ob["text"] = ocr_by_crop.get(str(crop), "")
        ocr_blocks.append(ob)
    kept_blocks, rule_removed = rule_filter(ocr_blocks, img_w, img_h)
    kept_rids = {b["region_id"] for b in kept_blocks}
    kept_pairs = [p for p in pairs if p[0] in kept_rids]

    # ---- VLM 校验（仅对保留的框）----
    vlm_result = {"texts": None, "status": "skipped", "raw_output": "", "elapsed": 0.0, "retries": 0}
    if vlm_enabled and kept_pairs:
        key = vlm_api_key or get_vlm_api_key()
        if key:
            t1 = time.time()
            try:
                vlm_result = vlm_fn([pil for _, _, _, pil in kept_pairs], api_key=key)
            except Exception as e:  # noqa: BLE001 — VLM 失败不拖垮 OCR 工位
                vlm_result = {"texts": None, "status": "failed", "raw_output": str(e),
                              "elapsed": time.time() - t1, "retries": 0}
        else:
            vlm_result["raw_output"] = "No VLM_API_KEY or CHAT_API_KEY configured"

    # ---- 构建 items（仅保留的框）----
    items = []
    vlm_texts = vlm_result.get("texts")
    vlm_idx = 0
    for rid, b, crop, _pil in kept_pairs:
        vlm_text = vlm_texts[vlm_idx] if (vlm_texts and vlm_idx < len(vlm_texts)) else None
        vlm_idx += 1
        baberu_text = ocr_by_crop.get(str(crop), "")
        item = {
            "region_id": rid,
            "bbox": b.get("bbox"),
            "text": baberu_text,  # 主文本 = baberu（VLM 仅作校验参考）
            "baberu_text": baberu_text,
            "vlm_text": vlm_text,
            "contained_in": b.get("contained_in"),
            "source_engines": b.get("source_engines", []),
            "vlm_status": vlm_result["status"],
            "page": page_idx,
        }
        for k in ("category", "bubble_type", "node_id", "sub_tier", "det_label", "confidence"):
            if b.get(k) is not None:
                item[k] = b[k]
        items.append(item)

    # ---- trace ----
    rule_removed_summary = {}
    for b in rule_removed:
        reason = b.get("filter_reason", "unknown")
        rule_removed_summary[reason] = rule_removed_summary.get(reason, 0) + 1
    artifacts.write_trace(artifacts_dir, page, "02_ocr", {
        "n_blocks_raw": len(pairs),
        "n_blocks_kept": len(kept_pairs),
        "n_blocks_rule_removed": len(rule_removed),
        "rule_removed_by_reason": rule_removed_summary,
        "rule_removed_details": [
            {"region_id": b.get("region_id"), "text": b.get("text", "")[:30],
             "reason": b.get("filter_reason")}
            for b in rule_removed
        ],
        "baberu_elapsed": round(baberu_elapsed, 2),
        "vlm_status": vlm_result["status"],
        "vlm_elapsed": round(vlm_result.get("elapsed", 0.0), 2),
        "vlm_retries": vlm_result.get("retries", 0),
        "baberu_vs_vlm_diff": [
            {"region_id": it["region_id"], "baberu": it["baberu_text"],
             "vlm": it["vlm_text"],
             "match": it["baberu_text"] == (it["vlm_text"] or "")}
            for it in items if it["vlm_text"] is not None
        ],
    })

    doc = artifacts.stamp({"items": items, "n_regions": len(items),
                           "vlm_status": vlm_result["status"],
                           "rule_filter": {
                               "raw": len(pairs), "kept": len(kept_pairs),
                               "removed": len(rule_removed),
                               "removed_by_reason": rule_removed_summary,
                           }}, work_id, page)
    write_json(artifacts_dir / f"{page}_canon.json", doc)
    return doc
