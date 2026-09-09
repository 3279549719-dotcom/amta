"""Q1 跨漫画验证：对月天新地检测结果跑 OCR（hayai），手动应用 first_token_conf<0.4 过滤。

由于 ocr_page 内置的 conf 过滤只对 source_engines==["rtdetr-v2-tiled"] 的框生效，
主链框不会被自动过滤。本脚本对所有检测框跑 OCR 后，手动从 canon 中提取
first_token_conf，应用 <0.4 阈值过滤，统计过滤效果并抽样保留框供人工验证。

输出：
  workspace/exp-q1-cross-manga/ocr/canon/page_{idx}.json
  workspace/exp-q1-cross-manga/ocr/crops/page_{idx}/...
  workspace/exp-q1-cross-manga/ocr/ocr_result.json
  workspace/exp-q1-cross-manga/ocr/sample_verification.json
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

# 清除代理，避免 OCR 模型下载走代理
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from amta.ocr_station import ocr_page  # noqa: E402

# ---- 配置 ----
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\月天新地")
DET_DIR = PROJECT_ROOT / "workspace" / "exp-q1-cross-manga" / "detection"
OCR_DIR = PROJECT_ROOT / "workspace" / "exp-q1-cross-manga" / "ocr"
CANON_DIR = OCR_DIR / "canon"
CROP_DIR = OCR_DIR / "crops"
CANON_DIR.mkdir(parents=True, exist_ok=True)
CROP_DIR.mkdir(parents=True, exist_ok=True)

WORK_ID = "exp-q1-cross-manga-ocr"
OCR_CONF_THRESHOLD = 0.4  # first_token_conf < 0.4 则过滤
SAMPLE_COUNT = 12  # 随机抽样保留框数量
RANDOM_SEED = 42


def load_detection(page_idx: int) -> dict | None:
    """加载单页检测结果。"""
    path = DET_DIR / f"page_{page_idx}_detection.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run_ocr_for_page(page_idx: int) -> dict | None:
    """对单页跑 OCR，返回 canon dict。"""
    det_doc = load_detection(page_idx)
    if det_doc is None:
        print(f"  p{page_idx}: 检测结果不存在，跳过")
        return None

    raw_path = RAW_DIR / f"{page_idx}.jpg"
    if not raw_path.exists():
        print(f"  p{page_idx}: 原图不存在，跳过")
        return None

    page_crop_dir = CROP_DIR / f"page_{page_idx}"
    page_crop_dir.mkdir(parents=True, exist_ok=True)

    n_blocks = det_doc["n_boxes"]
    print(f"  p{page_idx:2d}: {n_blocks} 框, 跑 OCR...", end=" ", flush=True)

    try:
        canon = ocr_page(
            WORK_ID, det_doc, raw_path, OCR_DIR,
            page_idx=page_idx, engine="hayai",
            vlm_enabled=False, rule_filter_enabled=False,
            crop_dir=page_crop_dir,
        )
        n_kept = canon.get("n_regions", 0)
        print(f"→ canon {n_kept} regions")
        return canon
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None


def extract_box_ocr_info(canon: dict, det_doc: dict) -> list[dict]:
    """从 canon 中提取每个检测框的 OCR 信息（first_token_conf 等）。

    canon.items 中的项与 det_doc.blocks 通过 region_id 对应。
    """
    items_by_rid = {item["region_id"]: item for item in canon.get("items", [])}
    results = []
    for block in det_doc.get("blocks", []):
        rid = block["region_id"]
        item = items_by_rid.get(rid)
        if item is None:
            # 框可能被 OCR 内置过滤掉（虽然主链框不会）
            results.append({
                "region_id": rid,
                "bbox": block["bbox"],
                "det_conf": block["confidence"],
                "ocr_text": "",
                "first_token_conf": None,
                "avg_conf": None,
                "status": "MISSING_IN_CANON",
            })
        else:
            results.append({
                "region_id": rid,
                "bbox": block["bbox"],
                "det_conf": block["confidence"],
                "ocr_text": item.get("text", ""),
                "first_token_conf": item.get("first_token_conf", 1.0),
                "avg_conf": item.get("avg_conf", 1.0),
                "low_ratio": item.get("low_ratio", 0.0),
                "status": "OCR_OK",
            })
    return results


def main():
    print("=" * 70)
    print("Q1 跨漫画验证：月天新地 OCR + first_token_conf 过滤分析")
    print("=" * 70)
    print(f"原图目录: {RAW_DIR}")
    print(f"检测结果: {DET_DIR}")
    print(f"OCR 输出: {OCR_DIR}")
    print(f"OCR 引擎: hayai")
    print(f"过滤阈值: first_token_conf < {OCR_CONF_THRESHOLD}")

    # 找到所有有检测结果的页
    det_files = sorted(DET_DIR.glob("page_*_detection.json"))
    page_indices = sorted(int(f.stem.replace("page_", "").replace("_detection", "")) for f in det_files)
    print(f"\n目标页: {len(page_indices)} 页 ({page_indices[0]}~{page_indices[-1]})")

    # ---- Step 1: 跑 OCR ----
    print(f"\n{'─' * 70}")
    print("Step 1: 对所有检测框跑 OCR")
    print(f"{'─' * 70}")

    all_canon = {}
    all_box_ocr = {}  # page_idx -> list[box_ocr_info]
    t0 = time.time()

    for page_idx in page_indices:
        canon = run_ocr_for_page(page_idx)
        if canon is not None:
            all_canon[page_idx] = canon
            det_doc = load_detection(page_idx)
            all_box_ocr[page_idx] = extract_box_ocr_info(canon, det_doc)

    ocr_elapsed = time.time() - t0
    print(f"\nOCR 完成，耗时 {ocr_elapsed:.1f}s ({ocr_elapsed / 60:.1f}min)")

    # ---- Step 2: 汇总所有框的 OCR 信息 ----
    print(f"\n{'─' * 70}")
    print("Step 2: 汇总所有框的 first_token_conf")
    print(f"{'─' * 70}")

    all_boxes = []
    for page_idx in sorted(all_box_ocr.keys()):
        for box in all_box_ocr[page_idx]:
            all_boxes.append({"page": page_idx, **box})

    total_boxes = len(all_boxes)
    print(f"\n总检测框数: {total_boxes}")

    # first_token_conf 分布
    confs = [b["first_token_conf"] for b in all_boxes if b["first_token_conf"] is not None]
    if confs:
        print(f"\n【first_token_conf 分布】")
        print(f"  min: {min(confs):.4f}")
        print(f"  max: {max(confs):.4f}")
        print(f"  mean: {sum(confs) / len(confs):.4f}")
        print(f"  median: {sorted(confs)[len(confs) // 2]:.4f}")

        thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        print(f"\n  不同阈值下的过滤数量：")
        for th in thresholds:
            n_below = sum(1 for c in confs if c < th)
            print(f"    first_conf < {th}: {n_below} 个 ({n_below / len(confs) * 100:.1f}%)")

    # ---- Step 3: 应用 first_token_conf < 0.4 过滤 ----
    print(f"\n{'─' * 70}")
    print(f"Step 3: 应用 first_token_conf < {OCR_CONF_THRESHOLD} 过滤")
    print(f"{'─' * 70}")

    filtered_out = [b for b in all_boxes
                    if b["first_token_conf"] is not None and b["first_token_conf"] < OCR_CONF_THRESHOLD]
    kept = [b for b in all_boxes
            if b["first_token_conf"] is not None and b["first_token_conf"] >= OCR_CONF_THRESHOLD]
    missing = [b for b in all_boxes if b["first_token_conf"] is None]

    n_filtered = len(filtered_out)
    n_kept = len(kept)
    filter_rate = n_filtered / total_boxes if total_boxes else 0

    print(f"\n  过滤前总框数: {total_boxes}")
    print(f"  被过滤 (first_conf<{OCR_CONF_THRESHOLD}): {n_filtered} ({filter_rate * 100:.1f}%)")
    print(f"  保留 (first_conf>={OCR_CONF_THRESHOLD}): {n_kept}")
    print(f"  缺失 OCR 结果: {len(missing)}")
    print(f"  过滤后保留率: {n_kept / total_boxes * 100:.1f}%")

    # 每页过滤前后对比
    print(f"\n  每页过滤前后对比:")
    print(f"  {'页':<5} {'过滤前':<8} {'过滤后':<8} {'过滤数':<8} {'过滤率':<8}")
    print("  " + "-" * 40)
    per_page_stats = []
    for page_idx in sorted(all_box_ocr.keys()):
        page_boxes = all_box_ocr[page_idx]
        n_total = len(page_boxes)
        n_filt = sum(1 for b in page_boxes
                     if b["first_token_conf"] is not None and b["first_token_conf"] < OCR_CONF_THRESHOLD)
        n_keep = n_total - n_filt
        rate = n_filt / n_total * 100 if n_total else 0
        per_page_stats.append({
            "page": page_idx, "before": n_total, "after": n_keep,
            "filtered": n_filt, "filter_rate": rate,
        })
        print(f"  p{page_idx:<4} {n_total:<8} {n_keep:<8} {n_filt:<8} {rate:<8.1f}%")

    # ---- Step 4: 被过滤框详情 ----
    if filtered_out:
        print(f"\n【被过滤框详情（{n_filtered} 个）— first_token_conf 升序】")
        print(f"  {'页':<5} {'ID':<6} {'det_conf':<10} {'first_conf':<12} {'OCR文本':<30}")
        print("  " + "-" * 65)
        for b in sorted(filtered_out, key=lambda x: x["first_token_conf"]):
            print(f"  p{b['page']:<4} {b['region_id']:<6} {b['det_conf']:<10.4f} "
                  f"{b['first_token_conf']:<12.4f} {b['ocr_text'][:28]:<30}")

    # ---- Step 5: 随机抽样保留框供人工验证 ----
    print(f"\n{'─' * 70}")
    print(f"Step 5: 随机抽样 {SAMPLE_COUNT} 个保留框供人工验证")
    print(f"{'─' * 70}")

    random.seed(RANDOM_SEED)
    sample_size = min(SAMPLE_COUNT, len(kept))
    sampled = random.sample(kept, sample_size)

    sample_results = []
    for b in sorted(sampled, key=lambda x: (x["page"], x["region_id"])):
        page_idx = b["page"]
        rid = b["region_id"]
        # 裁剪图路径
        crop_path = CROP_DIR / f"page_{page_idx}" / f"{rid}.png"
        sample_results.append({
            "page": page_idx,
            "region_id": rid,
            "bbox": b["bbox"],
            "det_conf": b["det_conf"],
            "first_token_conf": b["first_token_conf"],
            "ocr_text": b["ocr_text"],
            "crop_path": str(crop_path),
            "crop_exists": crop_path.exists(),
            "manual_verdict": None,  # 待人工填写
            "manual_note": "",
        })
        print(f"  p{page_idx} {rid}: det={b['det_conf']:.4f} "
              f"first_conf={b['first_token_conf']:.4f} "
              f"OCR='{b['ocr_text'][:25]}' crop={'✓' if crop_path.exists() else '✗'}")

    # ---- Step 6: 保存结果 ----
    print(f"\n{'─' * 70}")
    print("Step 6: 保存结果")
    print(f"{'─' * 70}")

    result = {
        "experiment": "q1_cross_manga_ocr",
        "manga": "月天新地",
        "ocr_engine": "hayai",
        "detect_conf_threshold": 0.5,
        "ocr_filter_threshold": OCR_CONF_THRESHOLD,
        "total_pages": len(page_indices),
        "total_boxes_before_filter": total_boxes,
        "total_boxes_after_filter": n_kept,
        "total_filtered": n_filtered,
        "filter_rate": filter_rate,
        "keep_rate": n_kept / total_boxes if total_boxes else 0,
        "first_token_conf_stats": {
            "min": min(confs) if confs else None,
            "max": max(confs) if confs else None,
            "mean": sum(confs) / len(confs) if confs else None,
            "median": sorted(confs)[len(confs) // 2] if confs else None,
        },
        "per_page_stats": per_page_stats,
        "filtered_boxes": filtered_out,
        "kept_boxes_count": n_kept,
        "ocr_elapsed_seconds": ocr_elapsed,
    }
    result_path = OCR_DIR / "ocr_result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  OCR 结果: {result_path}")

    sample_path = OCR_DIR / "sample_verification.json"
    sample_path.write_text(json.dumps(sample_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  抽样验证: {sample_path}")

    # 保存所有框的详细 OCR 信息
    all_boxes_path = OCR_DIR / "all_boxes_ocr.json"
    all_boxes_path.write_text(json.dumps(all_boxes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  全量框 OCR: {all_boxes_path}")

    print(f"\n{'=' * 70}")
    print(f"OCR 阶段完成。过滤前 {total_boxes} 框 → 过滤后 {n_kept} 框（过滤 {n_filtered}，{filter_rate*100:.1f}%）")
    print(f"下一步：人工验证抽样的 {sample_size} 个保留框，判断真文字/杂质")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
