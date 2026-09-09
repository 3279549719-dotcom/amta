"""Q1 探针：重跑 40 页 detect（开瓦片化），找出瓦片化新增框 + rule_filter 滤除框，汇总页数。

用法：uv run python scripts/probes/q1_tiling_garbled_audit.py
输出：workspace/exp-q1-tiling-garbled/ 下的 detection + 统计 JSON
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保 src 在 path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from amta.stations.detect_station import detect_page  # noqa: E402
from amta.guards.rule_filter import rule_filter  # noqa: E402
from amta.backends.ocr_engines import ocr_batch  # noqa: E402

RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
WORK_ID = "exp-q1-tiling-garbled"
OUT_DIR = PROJECT_ROOT / "workspace" / WORK_ID / "artifacts"
DET_DIR = OUT_DIR / "detection"
CROP_DIR = OUT_DIR / "crops"

# 跳过的页（p5/p40 不存在）
SKIP_PAGES = {5, 40}


def run_detect() -> dict:
    """跑全部页 detect，返回 {page_idx: detection_doc}"""
    DET_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    for page_idx in range(42):
        if page_idx in SKIP_PAGES:
            continue
        raw_path = RAW_DIR / f"{page_idx}.jpg"
        if not raw_path.exists():
            print(f"  [skip] p{page_idx} 原图不存在")
            continue
        print(f"  [detect] p{page_idx} ...", flush=True)
        doc = detect_page(
            WORK_ID, raw_path, DET_DIR,
            page_idx=page_idx, conf_threshold=0.7,
            tiling_enabled=True, tiling_cols=3, tiling_rows=4,
            tiling_conf=0.3, tiling_nms_iou=0.5, coverage_thresh=0.5,
        )
        results[page_idx] = doc
        n_total = doc["n_boxes"]
        n_tiled = sum(1 for b in doc["blocks"] if "rtdetr-v2-tiled" in b.get("source_engines", []))
        print(f"    p{page_idx}: total={n_total}, tiled_new={n_tiled}", flush=True)
    return results


def find_tiled_new_boxes(detect_results: dict) -> list[dict]:
    """找出所有瓦片化新增框（source_engines 包含 rtdetr-v2-tiled）"""
    boxes = []
    for page_idx, doc in detect_results.items():
        for b in doc["blocks"]:
            if "rtdetr-v2-tiled" in b.get("source_engines", []):
                boxes.append({
                    "page": page_idx,
                    "region_id": b["region_id"],
                    "bbox": b["bbox"],
                    "confidence": b.get("confidence", 0),
                    "bubble_type": b.get("bubble_type", ""),
                })
    return boxes


def run_ocr_and_filter(detect_results: dict) -> tuple[list[dict], list[dict]]:
    """对所有框跑 OCR + rule_filter（只剩 pure_punct/pure_number），返回 (kept, removed)"""
    CROP_DIR.mkdir(parents=True, exist_ok=True)
    all_removed = []
    all_kept = []

    for page_idx, doc in detect_results.items():
        blocks = doc["blocks"]
        if not blocks:
            continue
        print(f"  [ocr] p{page_idx}: {len(blocks)} boxes ...", flush=True)

        # 裁框
        from PIL import Image
        raw_path = RAW_DIR / f"{page_idx}.jpg"
        img = Image.open(raw_path)
        crops = []
        crop_paths = []
        for i, b in enumerate(blocks):
            x1, y1, x2, y2 = [int(v) for v in b["bbox"]]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(img.width, x2), min(img.height, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            crop = img.crop((x1, y1, x2, y2))
            crop_path = CROP_DIR / f"p{page_idx}_{b['region_id']}.png"
            crop.save(crop_path)
            crops.append(crop_path)
            crop_paths.append((b, crop_path))

        # OCR
        ocr_rows = ocr_batch([str(c) for c in crops], engine="hayai")
        ocr_by_crop = {r["crop"]: (r.get("ocr") or "").strip() for r in ocr_rows}

        # 组装 ocr_blocks
        ocr_blocks = []
        for b, crop_path in crop_paths:
            ob = dict(b)
            ob["text"] = ocr_by_crop.get(str(crop_path), "")
            ocr_blocks.append(ob)

        # rule_filter（只剩 pure_punct/pure_number）
        kept, removed = rule_filter(ocr_blocks, img.width, img.height)

        for b in removed:
            all_removed.append({
                "page": page_idx,
                "region_id": b["region_id"],
                "text": b.get("text", "")[:50],
                "filter_reason": b.get("filter_reason", ""),
                "source_engines": b.get("source_engines", []),
                "bubble_type": b.get("bubble_type", ""),
            })

        for b in kept:
            all_kept.append({
                "page": page_idx,
                "region_id": b["region_id"],
                "text": b.get("text", "")[:50],
                "source_engines": b.get("source_engines", []),
                "bubble_type": b.get("bubble_type", ""),
            })

        n_removed = len(removed)
        print(f"    p{page_idx}: kept={len(kept)}, removed={n_removed}", flush=True)
        if removed:
            for r in removed:
                print(f"      REMOVED: {r['region_id']} reason={r['filter_reason']} text='{r['text'][:30]}'", flush=True)

    return all_kept, all_removed


def main():
    print("=" * 60)
    print("Q1 探针：瓦片化新增框 + rule_filter 滤除框审计")
    print("=" * 60)

    # Step 1: detect
    print("\n[Step 1] 跑 40 页 detect（开瓦片化）...")
    detect_results = run_detect()

    # Step 2: 找出瓦片化新增框
    print("\n[Step 2] 找出瓦片化新增框...")
    tiled_boxes = find_tiled_new_boxes(detect_results)
    tiled_pages = sorted(set(b["page"] for b in tiled_boxes))
    print(f"  瓦片化新增框总数: {len(tiled_boxes)}")
    print(f"  分布页数: {tiled_pages}")
    for b in tiled_boxes:
        print(f"    p{b['page']} {b['region_id']} conf={b['confidence']:.3f} type={b['bubble_type']}")

    # Step 3: OCR + rule_filter
    print("\n[Step 3] 跑 OCR + rule_filter（只剩 pure_punct/pure_number）...")
    kept, removed = run_ocr_and_filter(detect_results)
    removed_pages = sorted(set(b["page"] for b in removed))
    print(f"\n  rule_filter 滤除总数: {len(removed)}")
    print(f"  分布页数: {removed_pages}")

    # Step 4: 汇总 25 个框对应的页数
    print("\n[Step 4] 汇总目标框页数...")
    target_pages = sorted(set(tiled_pages) | set(removed_pages))
    print(f"  瓦片化新增框页数: {len(tiled_pages)} 页")
    print(f"  rule_filter 滤除框页数: {len(removed_pages)} 页")
    print(f"  合并后需重跑的页数: {len(target_pages)} 页")
    print(f"  页数列表: {target_pages}")

    # 保存统计
    summary = {
        "tiled_new_boxes": tiled_boxes,
        "tiled_new_count": len(tiled_boxes),
        "tiled_new_pages": tiled_pages,
        "rule_filter_removed": removed,
        "rule_filter_removed_count": len(removed),
        "rule_filter_removed_pages": removed_pages,
        "target_pages": target_pages,
        "target_page_count": len(target_pages),
    }
    summary_path = OUT_DIR / "q1_audit_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  统计已保存: {summary_path}")

    print("\n" + "=" * 60)
    print("完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
