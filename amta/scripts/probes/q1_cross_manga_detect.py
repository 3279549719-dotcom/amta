"""Q1 跨漫画验证：对月天新地前20页跑 detect，conf_threshold=0.5。

目的：验证在单翼停留之地上得到的 detect conf=0.5 参数，
在另一本画风/排版不同的漫画上是否能稳定检出文字框且不过度产生假框。

输出：
  workspace/exp-q1-cross-manga/detection/page_{idx}_detection.json
  workspace/exp-q1-cross-manga/detection/summary.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from amta.stations.detect_station import RTDetrDetector  # noqa: E402

# ---- 配置 ----
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\月天新地")
OUT_DIR = PROJECT_ROOT / "workspace" / "exp-q1-cross-manga" / "detection"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CONF_THRESHOLD = 0.5
PAGE_RANGE = range(1, 21)  # 1.jpg ~ 20.jpg
WORK_ID = "exp-q1-cross-manga-detect"


def detect_page(page_idx: int, det: RTDetrDetector) -> dict:
    """对单页跑检测，返回标准 detection doc。"""
    raw_path = RAW_DIR / f"{page_idx}.jpg"
    if not raw_path.exists():
        print(f"  [skip] p{page_idx} 原图不存在: {raw_path}")
        return {"page": page_idx, "n_boxes": 0, "blocks": [], "error": "file_not_found"}

    blocks = det.detect(str(raw_path))
    doc = {
        "work_id": WORK_ID,
        "page": f"page_{page_idx}",
        "page_idx": page_idx,
        "conf_threshold": CONF_THRESHOLD,
        "n_boxes": len(blocks),
        "blocks": blocks,
    }
    # 保存单页结果
    out_path = OUT_DIR / f"page_{page_idx}_detection.json"
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def main():
    print("=" * 70)
    print(f"Q1 跨漫画验证：月天新地 detect (conf_threshold={CONF_THRESHOLD})")
    print("=" * 70)
    print(f"原图目录: {RAW_DIR}")
    print(f"页数范围: {PAGE_RANGE.start} ~ {PAGE_RANGE.stop - 1}")
    print(f"输出目录: {OUT_DIR}")

    det = RTDetrDetector(conf_threshold=CONF_THRESHOLD)

    all_results = {}
    total_boxes = 0
    t0 = time.time()

    for page_idx in PAGE_RANGE:
        print(f"  [detect] p{page_idx:2d} ...", end=" ", flush=True)
        doc = detect_page(page_idx, det)
        n = doc["n_boxes"]
        total_boxes += n
        all_results[page_idx] = doc
        print(f"→ {n} boxes")

    elapsed = time.time() - t0

    # ---- 统计 ----
    print(f"\n{'─' * 70}")
    print("检测统计")
    print(f"{'─' * 70}")
    print(f"  总页数: {len(all_results)}")
    print(f"  总检测框数: {total_boxes}")
    print(f"  平均每页框数: {total_boxes / len(all_results):.1f}")

    box_counts = [doc["n_boxes"] for doc in all_results.values()]
    print(f"  每页最少: {min(box_counts)}")
    print(f"  每页最多: {max(box_counts)}")

    # confidence 分布
    all_confs = []
    for doc in all_results.values():
        for b in doc["blocks"]:
            all_confs.append(b["confidence"])
    if all_confs:
        print(f"\n  检测框 confidence 分布:")
        print(f"    min: {min(all_confs):.4f}")
        print(f"    max: {max(all_confs):.4f}")
        print(f"    mean: {sum(all_confs) / len(all_confs):.4f}")
        print(f"    median: {sorted(all_confs)[len(all_confs) // 2]:.4f}")
        for lo, hi in [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]:
            cnt = sum(1 for c in all_confs if lo <= c < hi)
            print(f"    [{lo:.1f}, {hi:.1f}): {cnt} ({cnt / len(all_confs) * 100:.1f}%)")

    # 每页框数详情
    print(f"\n  每页框数:")
    for page_idx in sorted(all_results.keys()):
        print(f"    p{page_idx:2d}: {all_results[page_idx]['n_boxes']}")

    print(f"\n  耗时: {elapsed:.1f}s ({elapsed / 60:.1f}min)")

    # ---- 保存汇总 ----
    summary = {
        "experiment": "q1_cross_manga_detect",
        "manga": "月天新地",
        "conf_threshold": CONF_THRESHOLD,
        "page_range": [PAGE_RANGE.start, PAGE_RANGE.stop - 1],
        "total_pages": len(all_results),
        "total_boxes": total_boxes,
        "avg_boxes_per_page": total_boxes / len(all_results),
        "min_boxes_per_page": min(box_counts),
        "max_boxes_per_page": max(box_counts),
        "confidence_stats": {
            "min": min(all_confs) if all_confs else None,
            "max": max(all_confs) if all_confs else None,
            "mean": sum(all_confs) / len(all_confs) if all_confs else None,
            "median": sorted(all_confs)[len(all_confs) // 2] if all_confs else None,
        },
        "per_page_boxes": {str(p): all_results[p]["n_boxes"] for p in sorted(all_results.keys())},
        "elapsed_seconds": elapsed,
    }
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n汇总已保存: {summary_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
