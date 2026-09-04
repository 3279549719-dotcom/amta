"""批量探针: 11-20页方案A精修mask对比。

扫描11-20页的检测结果, 对有text_free框的页面跑精修mask, 生成对比图和汇总数据。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "src"))

from amta.text_mask_refiner import build_rect_mask, refine_text_mask  # noqa: E402

SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
ARTIFACTS_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "refine_mask_batch_11_20"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGE_RANGE = range(11, 21)  # 11-20


def make_comparison(img_rgb, rect_mask, refined_mask, page_name):
    """生成对比图: 原图 / 矩形mask叠加 / 精修mask叠加 / 差异图。"""
    h, w = img_rgb.shape[:2]
    target_h = 900
    scale = target_h / h

    def resize(im):
        return im.resize((int(im.width * scale), target_h), Image.LANCZOS)

    # 原图
    orig = Image.fromarray(img_rgb)

    # 矩形mask叠加 (红色)
    rect_overlay = orig.copy()
    rect_draw = ImageDraw.Draw(rect_overlay)
    rect_draw.bitmap((0, 0), Image.fromarray(rect_mask), fill=(255, 0, 0, 128))

    # 精修mask叠加 (蓝色)
    refined_overlay = orig.copy()
    refined_draw = ImageDraw.Draw(refined_overlay)
    refined_draw.bitmap((0, 0), Image.fromarray(refined_mask), fill=(0, 0, 255, 128))

    # 差异图 (精修有但矩形没有 = 绿色, 矩形有但精修没有 = 红色)
    diff = np.zeros_like(img_rgb)
    rect_bin = rect_mask > 128
    refined_bin = refined_mask > 128
    only_rect = rect_bin & ~refined_bin
    only_refined = refined_bin & ~rect_bin
    diff[only_rect] = [255, 100, 100]
    diff[only_refined] = [100, 255, 100]
    diff_img = Image.fromarray(diff)

    panels = [
        ("Original", orig),
        ("Rect Mask (red)", rect_overlay),
        ("Refined Mask (blue)", refined_overlay),
        ("Diff (green=refined only)", diff_img),
    ]

    pw = resize(panels[0][1]).width
    canvas = Image.new("RGB", (pw * 2, target_h * 2 + 60), (240, 240, 240))
    d = ImageDraw.Draw(canvas)
    for i, (label, im) in enumerate(panels):
        col = i % 2
        row = i // 2
        x = col * pw
        y = row * (target_h + 30)
        d.text((x + 8, y + 5), label, fill=(0, 0, 0))
        canvas.paste(resize(im), (x, y + 28))

    return canvas


def main():
    print("[batch] Plan A refined mask batch: pages 11-20")
    print(f"  Output: {OUT_DIR}")

    summary = {}
    pages_with_free = []

    for page_idx in PAGE_RANGE:
        page_name = f"page_{page_idx:02d}"
        det_path = ARTIFACTS_DIR / f"{page_name}_detection.json"

        if not det_path.exists():
            print(f"  {page_name}: detection not found, skip")
            continue

        with open(det_path, encoding="utf-8") as f:
            det = json.load(f)

        blocks = det.get("blocks") or det.get("regions") or []
        free_boxes = [b["bbox"] for b in blocks if b.get("bubble_type") == "text_free"]
        bubble_boxes = [b["bbox"] for b in blocks if b.get("bubble_type") == "text_bubble"]

        if not free_boxes:
            print(f"  {page_name}: no text_free boxes ({len(bubble_boxes)} bubble), skip")
            continue

        # 找对应的原始图片
        # detection.json 里可能有 image_meta 或 source_file
        raw_file = None
        if "image_meta" in det:
            raw_file = det["image_meta"].get("source_file") or det["image_meta"].get("filename")
        if not raw_file:
            # 尝试按文件名匹配: page_idx 对应的 jpg
            # page_11 = 12.jpg (0-indexed)
            raw_file = f"{page_idx - 1}.jpg"

        raw_path = SRC_DIR / raw_file
        if not raw_path.exists():
            # 尝试其他命名
            candidates = list(SRC_DIR.glob(f"*{page_idx - 1}*.jpg")) + list(SRC_DIR.glob(f"*{page_idx}*.jpg"))
            if candidates:
                raw_path = candidates[0]
            else:
                print(f"  {page_name}: raw image not found ({raw_file}), skip")
                continue

        print(f"  {page_name}: {len(free_boxes)} free boxes, {len(bubble_boxes)} bubble, raw={raw_path.name}")
        pages_with_free.append(page_name)

        img_pil = Image.open(raw_path).convert("RGB")
        img_rgb = np.array(img_pil)
        h, w = img_rgb.shape[:2]

        # 矩形 mask
        t0 = time.perf_counter()
        rect_mask = build_rect_mask((h, w), free_boxes, pad=4)
        rect_time = time.perf_counter() - t0

        # 精修 mask
        t0 = time.perf_counter()
        refined_mask = refine_text_mask(img_rgb, free_boxes, pad=4)
        refined_time = time.perf_counter() - t0

        rect_pixels = int((rect_mask > 128).sum())
        refined_pixels = int((refined_mask > 128).sum())
        reduction_pct = round((1 - refined_pixels / rect_pixels) * 100, 1) if rect_pixels > 0 else 0

        # IoU
        intersection = int(((rect_mask > 128) & (refined_mask > 128)).sum())
        union = int(((rect_mask > 128) | (refined_mask > 128)).sum())
        iou = round(intersection / union, 3) if union > 0 else 0

        summary[page_name] = {
            "raw_file": raw_path.name,
            "free_boxes": len(free_boxes),
            "bubble_boxes": len(bubble_boxes),
            "rect_pixels": rect_pixels,
            "refined_pixels": refined_pixels,
            "rect_ratio": round(rect_pixels / (h * w) * 100, 2),
            "refined_ratio": round(refined_pixels / (h * w) * 100, 2),
            "reduction_pct": reduction_pct,
            "iou": iou,
            "rect_time": round(rect_time, 4),
            "refined_time": round(refined_time, 4),
        }

        # 保存单独的 mask
        Image.fromarray(rect_mask).save(OUT_DIR / f"{page_name}_rect_mask.png")
        Image.fromarray(refined_mask).save(OUT_DIR / f"{page_name}_refined_mask.png")

        # 对比图
        comparison = make_comparison(img_rgb, rect_mask, refined_mask, page_name)
        comparison.save(OUT_DIR / f"{page_name}_comparison.png")

        print(f"    rect={rect_pixels:,} ({rect_pixels/(h*w)*100:.2f}%), "
              f"refined={refined_pixels:,} ({refined_pixels/(h*w)*100:.2f}%), "
              f"reduction={reduction_pct}%, iou={iou}, "
              f"time={refined_time:.3f}s")

    # 保存汇总
    with open(OUT_DIR / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # 统计
    if summary:
        avg_reduction = np.mean([s["reduction_pct"] for s in summary.values()])
        avg_iou = np.mean([s["iou"] for s in summary.values()])
        total_free = sum(s["free_boxes"] for s in summary.values())
        print("\n[batch] Summary:")
        print(f"  Pages with text_free: {len(summary)}/10")
        print(f"  Total text_free boxes: {total_free}")
        print(f"  Avg mask pixel reduction: {avg_reduction:.1f}%")
        print(f"  Avg IoU (rect vs refined): {avg_iou:.3f}")
        print(f"  Output: {OUT_DIR}")

    print("\n[batch] Done.")


if __name__ == "__main__":
    main()