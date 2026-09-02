"""Stage 2 OCR 工位 — detection + raw 页 → CanonArtifact（深模块）。

藏匿：裁框（region_id = region_id(page_idx, i)，与 detect 输出顺序一一对应）、
ocr_batch 分发（baberu fast path）、VLM contact sheet 批量校验、VLM key 解析
（amta.config）、双引擎合并（空 OCR 保留）、trace、save_canon（doc 化，修 F2）。
接缝：ocr_fn / vlm_fn 函数注入（内部接缝，测试用 fake）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PIL import Image

from amta import artifacts
from amta.config import get_vlm_api_key
from amta.paths import write_json


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
        # 优先用 block 自带 region_id（detect 输出单空间 page_{idx}_u{i:02d}），
        # 缺失（旧/评测 fixture 无 region_id）时按 index 推导同名 ID（修 F3 单空间）。
        rid = b.get("region_id") or artifacts.region_id(page_idx, i)
        crop = crop_dir / f"{rid}.png"
        pil_crop = img.crop((x1, y1, x2, y2))
        pil_crop.save(crop)
        out.append((rid, b, crop, pil_crop))
    return out


def ocr_page(work_id: str, det: dict, raw_page: Path, artifacts_dir: Path, *,
             page_idx: int, engine: str = "auto", vlm_enabled: bool = False,
             ocr_fn=None, vlm_fn=None, vlm_api_key: str | None = None,
             crop_dir: Path | str | None = None,
             fallback_ocr_fn=None) -> dict:
    """Stage 2 OCR 工位。

    fallback_ocr_fn: 可选第二引擎（宁滥勿缺兜底）。缺省按 engine 反向选择：
    engine=dashscope → auto(baberu fast path, 免费)；其余 → dashscope。测试传 fake。
    """
    from amta.ocr_engines import ocr_batch as _default_ocr
    from amta.ocr_engines import ocr_batch as _fallback_ocr
    from amta.vlm_verify import vlm_verify_batch as _default_vlm
    ocr_fn = ocr_fn or _default_ocr
    vlm_fn = vlm_fn or _default_vlm
    fallback_ocr_fn = fallback_ocr_fn or _fallback_ocr
    page = artifacts.page_key(page_idx)
    artifacts_dir = Path(artifacts_dir)

    blocks = det.get("blocks", [])
    # crop_dir 缺省落 artifacts/crops；显式传入（eval_stage2 per-page 目录）则尊重（避免静默回归）
    crop_dir = Path(crop_dir) if crop_dir else artifacts_dir / "crops"
    pairs = _crop_by_region(raw_page, blocks, page_idx, crop_dir)
    if not pairs:
        raise RuntimeError(f"02_ocr: no valid bbox on {page} (source {det.get('page', '?')})")

    t0 = time.time()
    ocr_rows = ocr_fn([str(c) for _, _, c, _ in pairs], engine=engine)
    ocr_by_crop = {r["crop"]: (r.get("ocr") or "").strip() for r in ocr_rows}
    # 双引擎兜底（抄 manga-image-translator mocr，宁滥勿缺）：主引擎吐空的 region，
    # 用另一引擎逐个补；仍空则保留空串交下游 needs_review，绝不静默丢框。
    # 备选引擎：主引擎非 dashscope 时副=dashscope；主=dashscope 时副=auto(baberu, 免费)。
    empty_crops = [str(c) for _, _, c, _ in pairs if not ocr_by_crop.get(str(c))]
    if empty_crops:
        fallback_engine = "dashscope" if engine != "dashscope" else "auto"  # auto=baberu fast path
        print(f"[ocr_station] 空串回退 {fallback_engine}: {len(empty_crops)} crops", file=sys.stderr)
        try:
            fb = fallback_ocr_fn(empty_crops, engine=fallback_engine)
            for r in fb:
                t = (r.get("ocr") or "").strip()
                if t:
                    ocr_by_crop[r["crop"]] = t
        except Exception as e:  # noqa: BLE001
            print(f"[ocr_station] {fallback_engine} 兜底失败: {e}", file=sys.stderr)
    baberu_elapsed = time.time() - t0

    vlm_result = {"texts": None, "status": "skipped", "raw_output": "", "elapsed": 0.0, "retries": 0}
    if vlm_enabled:
        key = vlm_api_key or get_vlm_api_key()
        if key:
            t1 = time.time()
            try:
                vlm_result = vlm_fn([pil for _, _, _, pil in pairs], api_key=key)
            except Exception as e:  # noqa: BLE001 — VLM 失败不拖垮 OCR 工位
                vlm_result = {"texts": None, "status": "failed", "raw_output": str(e),
                              "elapsed": time.time() - t1, "retries": 0}
        else:
            vlm_result["raw_output"] = "No VLM_API_KEY or CHAT_API_KEY configured"

    items = []
    vlm_texts = vlm_result.get("texts")
    for i, (rid, b, crop, _pil) in enumerate(pairs):
        vlm_text = vlm_texts[i] if (vlm_texts and i < len(vlm_texts)) else None
        item = {
            "region_id": rid,
            "bbox": b.get("bbox"),
            "baberu_text": ocr_by_crop.get(str(crop), ""),
            "vlm_text": vlm_text,
            "contained_in": b.get("contained_in"),
            "source_engines": b.get("source_engines", []),
            "vlm_status": vlm_result["status"],
            "page": page_idx,
        }
        for k in ("category", "bubble_type", "node_id", "sub_tier"):
            if b.get(k) is not None:
                item[k] = b[k]
        items.append(item)

    artifacts.write_trace(artifacts_dir, page, "02_ocr", {
        "n_blocks": len(pairs),
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
                           "vlm_status": vlm_result["status"]}, work_id, page)
    write_json(artifacts_dir / f"{page}_canon.json", doc)  # 盘上即 doc（修 F2）
    return doc
