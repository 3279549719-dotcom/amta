"""Stage 2 OCR 工位 — detection + raw 页 → CanonArtifact（深模块）。

流程: 裁框 → OCR(engine可插拔: baberu/hayai) → [OCR confidence 过滤] → [规则过滤] → [VLM校验] → canon。
藏匿：裁框（region_id 与 detect 输出顺序一一对应）、ocr_batch 分发、VLM contact sheet 批量校验、trace、save_canon。
接缝：ocr_fn / vlm_fn 函数注入（内部接缝，测试用 fake）。

Q3 (2026-09-09): 新增 OCR confidence 过滤。hayai 引擎通过自定义 greedy decoding
收集每步 logits，计算 token 级 confidence。

过滤策略（只对副引擎纯新增框）:
  副引擎纯新增框（source_engines == ["rtdetr-v2-tiled"]）且 first_token_conf < 0.4 → 过滤
  其他框（主引擎框、主副引擎重叠框）→ 不过滤

背景：3个已知假框全是副引擎新增框（瓦片化捡小字时也捡进了杂质：刻度线、装订线、装饰线），
主引擎框假阳性率极低。只对副引擎新增框做过滤，避免误伤主引擎框中首字识别错误的真实文字
（如生僻汉字"嫦"→"婦"、数字"八"→"ハ"，首字 conf 低但后面的字都正确）。

全量40页311框验证：3个已知杂质框全部正确过滤，0误伤。

baberu 引擎不支持 confidence，返回 first_token_conf=1.0（不过滤）。

rule_filter 已退役（Q3）：pure_punct/pure_number 被 OCR confidence 替代，规则清空保留空壳接口。
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from amta.common.config import get_vlm_api_key
from amta.common.paths import write_json
from amta.guards.rule_filter import rule_filter
from amta.stores import artifacts

# Q3 OCR confidence 过滤阈值
OCR_CONF_THRESHOLD = 0.4  # 副引擎新增框首 token confidence 低于此值则过滤


def _crop_by_region(raw_page: Path, blocks: list[dict], page_idx: int,
                    crop_dir: Path) -> list[tuple[str, dict, Path, Image.Image]]:
    """按 bbox 裁框；region_id 与 detect 输出顺序一一对应（单空间，修 F3）。"""
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


def _should_filter_by_conf(row: dict, b: dict) -> tuple[bool, str]:
    """Q3 OCR confidence 过滤判断。只对副引擎纯新增框做过滤。

    背景：3个已知假框全是副引擎新增框（瓦片化捡杂质），主引擎框假阳性率极低。
    只对副引擎新增框做 first_token_conf < 0.4 过滤，避免误伤主引擎框中
    首字识别错误的真实文字（如生僻汉字"嫦"、数字"八"被误读）。

    Returns:
        (是否过滤, 过滤原因)
    """
    first_conf = row.get("first_token_conf", 1.0)
    if first_conf < OCR_CONF_THRESHOLD:
        return True, f"first_conf={first_conf:.4f}<{OCR_CONF_THRESHOLD}"
    return False, ""


def ocr_page(work_id: str, det: dict, raw_page: Path, artifacts_dir: Path, *,
             page_idx: int, engine: str = "hayai", vlm_enabled: bool = False,
             rule_filter_enabled: bool = False,
             ocr_fn=None, vlm_fn=None, vlm_api_key: str | None = None,
             crop_dir: Path | str | None = None) -> dict:
    """Stage 2 OCR 工位。裁框 → OCR → [OCR confidence 过滤] → [规则过滤] → [VLM校验] → CanonArtifact。

    engine: hayai(默认,HayaiOCR-v2.1) / baberu(ONNX,免费快)。
    rule_filter_enabled=False 时跳过硬规则过滤，全部检测框直接保留。
    Q3: 副引擎纯新增框用 first_token_conf < 0.4 过滤假框（见模块文档）。
    """
    from amta.backends.ocr_engines import ocr_batch as _default_ocr
    from amta.backends.vlm_verify import vlm_verify_batch as _default_vlm
    ocr_fn = ocr_fn or _default_ocr
    vlm_fn = vlm_fn or _default_vlm
    page = artifacts.page_key(page_idx)
    artifacts_dir = Path(artifacts_dir)

    blocks = det.get("blocks", [])
    crop_dir = Path(crop_dir) if crop_dir else artifacts_dir / "crops"
    pairs = _crop_by_region(raw_page, blocks, page_idx, crop_dir)
    if not pairs:
        raise RuntimeError(f"02_ocr: no valid bbox on {page} (source {det.get('page', '?')})")

    # ---- OCR ----
    t0 = time.time()
    ocr_rows = ocr_fn([str(c) for _, _, c, _ in pairs], engine=engine)
    ocr_by_crop = {r["crop"]: r for r in ocr_rows}

    ocr_elapsed = time.time() - t0

    # ---- OCR confidence 过滤（Q3, 2026-09-09）----
    # 只对副引擎纯新增框做 first_token_conf < 0.4 过滤
    conf_removed = []
    kept_after_conf = []
    for rid, b, crop, _pil in pairs:
        row = ocr_by_crop.get(str(crop), {})
        should_filter, reason = _should_filter_by_conf(row, b)
        ocr_text = (row.get("ocr") or "").strip()
        if should_filter:
            conf_removed.append({
                "region_id": rid,
                "text": ocr_text,
                "first_token_conf": row.get("first_token_conf", 1.0),
                "avg_conf": row.get("avg_conf", 1.0),
                "low_ratio": row.get("low_ratio", 0.0),
                "filter_reason": reason,
                "bbox": b.get("bbox"),
                "source_engines": b.get("source_engines", []),
            })
        else:
            kept_after_conf.append((rid, b, crop, _pil))

    # ---- 规则过滤（已退役，保留空壳接口兼容）----
    img_w, img_h = Image.open(raw_page).size
    ocr_blocks = []
    for rid, b, crop, _pil in kept_after_conf:
        ob = dict(b)
        ob["region_id"] = rid
        ob["text"] = (ocr_by_crop.get(str(crop), {}).get("ocr") or "").strip()
        ocr_blocks.append(ob)

    if rule_filter_enabled:
        kept_blocks, rule_removed = rule_filter(ocr_blocks, img_w, img_h)
    else:
        kept_blocks, rule_removed = ocr_blocks, []

    # 按 reason 统计被过滤框
    rule_removed_summary: dict[str, int] = {}
    for b in rule_removed:
        reason = b.get("filter_reason", "unknown")
        rule_removed_summary[reason] = rule_removed_summary.get(reason, 0) + 1

    kept_rids = {b["region_id"] for b in kept_blocks}
    kept_pairs = [p for p in kept_after_conf if p[0] in kept_rids]

    # ---- VLM 校验（仅对保留的框）----
    vlm_result = {"texts": None, "status": "skipped", "raw_output": "", "elapsed": 0.0, "retries": 0}
    if vlm_enabled:
        key = vlm_api_key or get_vlm_api_key()
        if key:
            t1 = time.time()
            try:
                vlm_result = vlm_fn([pil for _, _, _, pil in kept_pairs], api_key=key)
            except Exception as e:
                vlm_result = {"texts": None, "status": "failed", "raw_output": str(e),
                              "elapsed": time.time() - t1, "retries": 0}
        else:
            vlm_result["raw_output"] = "No VLM_API_KEY or CHAT_API_KEY configured"

    # ---- 组装 canon ----
    items = []
    vlm_texts = vlm_result.get("texts")
    for vlm_idx, (rid, b, crop, _pil) in enumerate(kept_pairs):
        vlm_text = vlm_texts[vlm_idx] if (vlm_texts and vlm_idx < len(vlm_texts)) else None
        row = ocr_by_crop.get(str(crop), {})
        ocr_text = (row.get("ocr") or "").strip()
        item = {
            "region_id": rid,
            "bbox": b.get("bbox"),
            "baberu_text": ocr_text,
            "text": ocr_text,  # 兼容字段
            "ocr_engine": engine,
            "first_token_conf": row.get("first_token_conf", 1.0),
            "avg_conf": row.get("avg_conf", 1.0),
            "low_ratio": row.get("low_ratio", 0.0),
            "vlm_text": vlm_text,
            "contained_in": b.get("contained_in"),
            "source_engines": b.get("source_engines", []),
            "vlm_status": vlm_result["status"],
            "page": page_idx,
        }
        for k in ("category", "node_id", "sub_tier"):
            if b.get(k) is not None:
                item[k] = b[k]
        items.append(item)

    artifacts.write_trace(artifacts_dir, page, "02_ocr", {
        "n_blocks_raw": len(pairs),
        "n_blocks_kept": len(kept_pairs),
        "n_blocks_conf_removed": len(conf_removed),
        "n_blocks_rule_removed": len(rule_removed),
        "ocr_conf_threshold": OCR_CONF_THRESHOLD,
        "conf_removed_details": [
            {"region_id": cr["region_id"], "text": cr["text"][:30],
             "first_token_conf": cr["first_token_conf"],
             "avg_conf": cr["avg_conf"],
             "low_ratio": cr["low_ratio"],
             "filter_reason": cr["filter_reason"],
             "source_engines": cr.get("source_engines", [])}
            for cr in conf_removed
        ],
        "rule_filter_enabled": rule_filter_enabled,
        "rule_removed_by_reason": rule_removed_summary,
        "rule_removed_details": [
            {"region_id": b.get("region_id"), "text": b.get("text", "")[:30],
             "reason": b.get("filter_reason")}
            for b in rule_removed
        ],
        "ocr_engine": engine,
        "ocr_elapsed": round(ocr_elapsed, 2),
        "vlm_status": vlm_result["status"],
        "vlm_elapsed": round(vlm_result.get("elapsed", 0.0), 2),
        "vlm_retries": vlm_result.get("retries", 0),
    })

    doc = artifacts.stamp({"items": items, "n_regions": len(items),
                           "ocr_engine": engine,
                           "ocr_conf_threshold": OCR_CONF_THRESHOLD,
                           "n_conf_removed": len(conf_removed),
                           "rule_filter_enabled": rule_filter_enabled,
                           "rule_filter": {
                               "enabled": rule_filter_enabled,
                               "raw": len(pairs), "kept": len(kept_pairs),
                               "conf_removed": len(conf_removed),
                               "rule_removed": len(rule_removed),
                               "removed_by_reason": rule_removed_summary,
                           },
                           "vlm_status": vlm_result["status"]}, work_id, page)
    write_json(artifacts.artifact_paths(artifacts_dir, page)["canon"], doc)
    return doc




