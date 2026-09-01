"""Stage 2 OCR 工位 — detection + raw 页 → CanonArtifact（深模块）。

最终选型：baberu-OCR（本地 ONNX）。VLM contact sheet 校验已废弃。
藏匿：裁框（region_id 与 detect 输出顺序一一对应）、baberu 批量 OCR、
trace、save_canon（doc 化）。
接缝：ocr_fn 函数注入（内部接缝，测试用 fake）。
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from amta import artifacts
from amta.paths import write_json


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
             page_idx: int, ocr_fn=None,
             crop_dir: Path | str | None = None) -> dict:
    """单页 OCR：裁框 → baberu 批量识别 → CanonArtifact（doc 信封）。"""
    from amta.ocr_engines import ocr_batch as _default_ocr
    ocr_fn = ocr_fn or _default_ocr
    page = artifacts.page_key(page_idx)
    artifacts_dir = Path(artifacts_dir)

    blocks = det.get("blocks", [])
    crop_dir = Path(crop_dir) if crop_dir else artifacts_dir / "crops"
    pairs = _crop_by_region(raw_page, blocks, page_idx, crop_dir)
    if not pairs:
        raise RuntimeError(f"02_ocr: no valid bbox on {page} (source {det.get('page', '?')})")

    t0 = time.time()
    ocr_rows = ocr_fn([str(c) for _, _, c, _ in pairs])
    ocr_by_crop = {r["crop"]: (r.get("ocr") or "").strip() for r in ocr_rows}
    elapsed = time.time() - t0

    items = []
    for rid, b, crop, _pil in pairs:
        ocr_text = ocr_by_crop.get(str(crop), "")
        item = {
            "region_id": rid,
            "bbox": b.get("bbox"),
            "text": ocr_text,
            "baberu_text": ocr_text,  # 向后兼容（下游同时支持 text/baberu_text）
            "contained_in": b.get("contained_in"),
            "source_engines": b.get("source_engines", []),
            "page": page_idx,
        }
        for k in ("category", "bubble_type", "node_id", "sub_tier", "det_label", "confidence"):
            if b.get(k) is not None:
                item[k] = b[k]
        items.append(item)

    artifacts.write_trace(artifacts_dir, page, "02_ocr", {
        "n_blocks": len(pairs),
        "elapsed": round(elapsed, 2),
    })

    doc = artifacts.stamp({"items": items, "n_regions": len(items)}, work_id, page)
    write_json(artifacts_dir / f"{page}_canon.json", doc)
    return doc
