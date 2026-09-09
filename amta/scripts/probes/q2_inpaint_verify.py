"""Q2 验证实验：只跑 inpaint 阶段，验证当前策略（矩形 mask + Lama）效果。

输入: output/data/ocr_check_html/{11..20}.jpg + exp-q1-tiling-garbled detection.json
输出: workspace/q2-inpaint-verify/{page}_clean.png + {page}_mask.png + summary.json
指标: pixel_diff_ratio (clean vs raw 像素差异比例), mask_coverage (mask 白色像素占比)
"""
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

from amta.inpaint.inpaint_station import _build_mask_image, _get_inpainter
from amta.common.paths import read_json

RAW_DIR = Path(r"E:\manga translator agent\amta\output\data\ocr_check_html")
DET_DIR = Path(r"E:\manga translator agent\amta\workspace\exp-q1-tiling-garbled\artifacts\detection")
OUT_DIR = Path(r"E:\manga translator agent\amta\workspace\q2-inpaint-verify")

PAGES = list(range(11, 21))  # 11-20, 10页


def pixel_diff_ratio(a: Image.Image, b: Image.Image) -> float:
    """clean vs raw 像素差异比例。"""
    if a.size != b.size:
        return 1.0
    hist = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L").histogram()
    changed = sum(hist[1:])
    return round(changed / (a.width * a.height), 4)


def mask_coverage(mask: Image.Image) -> float:
    """mask 白色像素占比（要修复的区域比例）。"""
    arr = np.array(mask.convert("L"))
    white = np.sum(arr > 128)
    return round(white / arr.size, 4)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    inpainter = _get_inpainter()
    summary = []

    for page in PAGES:
        raw_path = RAW_DIR / f"{page}.jpg"
        det_path = DET_DIR / f"page_{page}_detection.json"
        if not raw_path.exists() or not det_path.exists():
            print(f"  skip page_{page}: missing raw or det")
            continue

        det = read_json(det_path)
        raw_img = Image.open(raw_path).convert("RGB")
        regions = det.get("blocks") or []
        bboxes = [r["bbox"] for r in regions if r.get("bbox")]

        t0 = time.perf_counter()

        # 当前策略: 矩形 mask (refine=False) + Lama inpaint
        mask_img = _build_mask_image(raw_img, bboxes, refine=False)
        inpainted = inpainter.inpaint(raw_img, mask_img)
        if inpainted.size != raw_img.size:
            print(f"  page_{page}: inpaint size mismatch {inpainted.size} vs {raw_img.size}")
            continue

        elapsed = round(time.perf_counter() - t0, 2)

        # 保存 clean 图和 mask 图
        clean_path = OUT_DIR / f"page_{page}_clean.png"
        mask_path = OUT_DIR / f"page_{page}_mask.png"
        inpainted.save(clean_path)
        mask_img.save(mask_path)

        # 指标
        diff = pixel_diff_ratio(inpainted, raw_img)
        cov = mask_coverage(mask_img)
        n_bubble = sum(1 for r in regions if r.get("bubble_type") == "text_bubble")
        n_free = sum(1 for r in regions if r.get("bubble_type") == "text_free")

        entry = {
            "page": page,
            "n_boxes": len(bboxes),
            "n_text_bubble": n_bubble,
            "n_text_free": n_free,
            "mask_coverage": cov,
            "pixel_diff_ratio": diff,
            "elapsed_s": elapsed,
            "clean_image": str(clean_path.name),
            "mask_image": str(mask_path.name),
        }
        summary.append(entry)
        print(f"  page_{page}: {len(bboxes)} boxes (bubble={n_bubble}, free={n_free}), "
              f"mask_cov={cov}, diff={diff}, {elapsed}s")

    # 汇总
    if summary:
        avg_cov = round(np.mean([e["mask_coverage"] for e in summary]), 4)
        avg_diff = round(np.mean([e["pixel_diff_ratio"] for e in summary]), 4)
        avg_time = round(np.mean([e["elapsed_s"] for e in summary]), 2)
        total_boxes = sum(e["n_boxes"] for e in summary)
        total_bubble = sum(e["n_text_bubble"] for e in summary)
        total_free = sum(e["n_text_free"] for e in summary)

        print(f"\n{'='*60}")
        print(f"汇总: {len(summary)} 页, {total_boxes} 框 (bubble={total_bubble}, free={total_free})")
        print(f"  平均 mask 覆盖率: {avg_cov} ({avg_cov*100:.1f}% 像素被标记为修复)")
        print(f"  平均像素差异率: {avg_diff} ({avg_diff*100:.1f}% 像素被改变)")
        print(f"  平均耗时: {avg_time}s/页")
        print(f"  clean 图输出: {OUT_DIR}")
        print(f"{'='*60}")

        summary_path = OUT_DIR / "summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump({
                "pages": summary,
                "summary": {
                    "n_pages": len(summary),
                    "total_boxes": total_boxes,
                    "total_bubble": total_bubble,
                    "total_free": total_free,
                    "avg_mask_coverage": avg_cov,
                    "avg_pixel_diff_ratio": avg_diff,
                    "avg_elapsed_s": avg_time,
                },
            }, f, ensure_ascii=False, indent=2)
        print(f"  summary 保存: {summary_path}")


if __name__ == "__main__":
    main()
