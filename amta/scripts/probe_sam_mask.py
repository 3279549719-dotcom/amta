"""方案B: SAM框提示像素级分割探针。

用RT-DETR检测框作为box_prompt调用SAM, 生成像素级mask。
与方案A(传统方法精修)对比。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "src"))

from amta.text_mask_refiner import build_rect_mask, refine_text_mask  # noqa: E402

SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
ARTIFACTS_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "sam_mask_probe"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MODEL_PATH = ROOT / "models" / "sam_vit_b_01ec64.pth"

PAGE_RANGE = range(11, 21)


def load_sam_predictor(model_path: Path):
    """加载SAM模型。"""
    from segment_anything import sam_model_registry, SamPredictor

    print(f"[sam] Loading SAM ViT-B from {model_path}...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  device: {device}")

    sam = sam_model_registry["vit_b"](checkpoint=str(model_path))
    sam.to(device)
    predictor = SamPredictor(sam)
    print("[sam] Model loaded.")
    return predictor


def sam_segment_boxes(predictor, img_rgb: np.ndarray, boxes: list[list[float]]) -> np.ndarray:
    """用SAM对每个框做像素级分割, 合并mask。

    Args:
        predictor: SamPredictor
        img_rgb: 全页RGB图像
        boxes: [[x1, y1, x2, y2], ...]

    Returns:
        全页mask (H, W), 255=文字像素, 0=背景
    """
    h, w = img_rgb.shape[:2]
    combined_mask = np.zeros((h, w), dtype=np.uint8)

    predictor.set_image(img_rgb)

    for i, box in enumerate(boxes):
        x1, y1, x2, y2 = [float(v) for v in box]
        # SAM box prompt 格式: [x1, y1, x2, y2]
        input_box = np.array([[x1, y1, x2, y2]])

        masks, scores, _ = predictor.predict(
            point_coords=None,
            point_labels=None,
            box=input_box,
            multimask_output=True,  # 返回3个候选mask
        )

        # 选择置信度最高的mask
        best_idx = np.argmax(scores)
        best_mask = masks[best_idx]
        best_score = scores[best_idx]

        combined_mask[best_mask] = 255

        if i < 3:  # 只打印前3个框的详情
            print(f"    box {i}: score={best_score:.3f}, mask_pixels={int(best_mask.sum()):,}")

    return combined_mask


def make_ab_comparison(img_rgb, rect_mask, plan_a_mask, plan_b_mask, page_name):
    """生成A/B对比图: 原图 / 矩形mask / 方案A / 方案B / A差异 / B差异。"""
    h, w = img_rgb.shape[:2]
    target_h = 800
    scale = target_h / h

    def resize(im):
        return im.resize((int(im.width * scale), target_h), Image.LANCZOS)

    orig = Image.fromarray(img_rgb)

    def overlay_mask(im, mask, color):
        overlay = im.copy()
        d = ImageDraw.Draw(overlay)
        d.bitmap((0, 0), Image.fromarray(mask), fill=color)
        return overlay

    rect_overlay = overlay_mask(orig, rect_mask, (255, 0, 0, 128))
    a_overlay = overlay_mask(orig, plan_a_mask, (0, 0, 255, 128))
    b_overlay = overlay_mask(orig, plan_b_mask, (0, 255, 0, 128))

    # A vs B 差异
    a_bin = plan_a_mask > 128
    b_bin = plan_b_mask > 128
    only_a = a_bin & ~b_bin
    only_b = b_bin & ~a_bin
    both = a_bin & b_bin

    diff = np.zeros_like(img_rgb)
    diff[only_a] = [0, 0, 255]    # 蓝: 只有A
    diff[only_b] = [0, 255, 0]    # 绿: 只有B
    diff[both] = [255, 255, 0]    # 黄: 两者都有
    diff_img = Image.fromarray(diff)

    panels = [
        ("Original", orig),
        ("Rect Mask (red)", rect_overlay),
        ("Plan A: Traditional (blue)", a_overlay),
        ("Plan B: SAM (green)", b_overlay),
        ("A vs B Diff (blue=A only, green=B only, yellow=both)", diff_img),
    ]

    pw = resize(panels[0][1]).width
    cols = 3
    rows = (len(panels) + cols - 1) // cols
    canvas = Image.new("RGB", (pw * cols, target_h * rows + 30 * rows), (240, 240, 240))
    d = ImageDraw.Draw(canvas)
    for i, (label, im) in enumerate(panels):
        col = i % cols
        row = i // cols
        x = col * pw
        y = row * (target_h + 30)
        d.text((x + 8, y + 5), label, fill=(0, 0, 0))
        canvas.paste(resize(im), (x, y + 28))

    return canvas


def main():
    print(f"[sam] Plan B: SAM box-prompt segmentation")
    print(f"  Model: {MODEL_PATH}")
    print(f"  Pages: 11-20")

    if not MODEL_PATH.exists():
        print(f"[sam] ERROR: model not found at {MODEL_PATH}")
        print("  Please download first: https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth")
        return

    predictor = load_sam_predictor(MODEL_PATH)

    summary = {}

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

        if not free_boxes:
            print(f"  {page_name}: no text_free boxes, skip")
            continue

        # 找原始图片
        raw_file = f"{page_idx - 1}.jpg"
        raw_path = SRC_DIR / raw_file
        if not raw_path.exists():
            candidates = list(SRC_DIR.glob(f"*{page_idx - 1}*.jpg")) + list(SRC_DIR.glob(f"*{page_idx}*.jpg"))
            if candidates:
                raw_path = candidates[0]
            else:
                print(f"  {page_name}: raw image not found, skip")
                continue

        print(f"\n  {page_name}: {len(free_boxes)} free boxes, raw={raw_path.name}")

        img_pil = Image.open(raw_path).convert("RGB")
        img_rgb = np.array(img_pil)
        h, w = img_rgb.shape[:2]

        # 矩形 mask
        rect_mask = build_rect_mask((h, w), free_boxes, pad=4)

        # 方案A: 传统方法精修
        t0 = time.perf_counter()
        plan_a_mask = refine_text_mask(img_rgb, free_boxes, pad=4)
        plan_a_time = time.perf_counter() - t0

        # 方案B: SAM
        t0 = time.perf_counter()
        plan_b_mask = sam_segment_boxes(predictor, img_rgb, free_boxes)
        plan_b_time = time.perf_counter() - t0

        rect_pixels = int((rect_mask > 128).sum())
        a_pixels = int((plan_a_mask > 128).sum())
        b_pixels = int((plan_b_mask > 128).sum())

        # A vs B IoU
        a_bin = plan_a_mask > 128
        b_bin = plan_b_mask > 128
        intersection = int((a_bin & b_bin).sum())
        union = int((a_bin | b_bin).sum())
        ab_iou = round(intersection / union, 3) if union > 0 else 0

        # 与矩形的IoU
        rect_bin = rect_mask > 128
        a_rect_iou = round(int((a_bin & rect_bin).sum()) / int((a_bin | rect_bin).sum()), 3) if (a_bin | rect_bin).sum() > 0 else 0
        b_rect_iou = round(int((b_bin & rect_bin).sum()) / int((b_bin | rect_bin).sum()), 3) if (b_bin | rect_bin).sum() > 0 else 0

        summary[page_name] = {
            "raw_file": raw_path.name,
            "free_boxes": len(free_boxes),
            "rect_pixels": rect_pixels,
            "plan_a_pixels": a_pixels,
            "plan_b_pixels": b_pixels,
            "plan_a_reduction_pct": round((1 - a_pixels / rect_pixels) * 100, 1) if rect_pixels > 0 else 0,
            "plan_b_reduction_pct": round((1 - b_pixels / rect_pixels) * 100, 1) if rect_pixels > 0 else 0,
            "ab_iou": ab_iou,
            "a_rect_iou": a_rect_iou,
            "b_rect_iou": b_rect_iou,
            "plan_a_time": round(plan_a_time, 3),
            "plan_b_time": round(plan_b_time, 3),
        }

        print(f"    rect={rect_pixels:,}, A={a_pixels:,} (reduce {summary[page_name]['plan_a_reduction_pct']}%), "
              f"B={b_pixels:,} (reduce {summary[page_name]['plan_b_reduction_pct']}%)")
        print(f"    A/B IoU={ab_iou}, A time={plan_a_time:.3f}s, B time={plan_b_time:.3f}s")

        # 保存单独的 mask
        Image.fromarray(plan_a_mask).save(OUT_DIR / f"{page_name}_plan_a_mask.png")
        Image.fromarray(plan_b_mask).save(OUT_DIR / f"{page_name}_plan_b_mask.png")

        # A/B 对比图
        comparison = make_ab_comparison(img_rgb, rect_mask, plan_a_mask, plan_b_mask, page_name)
        comparison.save(OUT_DIR / f"{page_name}_ab_comparison.png")

    # 保存汇总
    with open(OUT_DIR / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # 统计
    if summary:
        avg_a_reduction = np.mean([s["plan_a_reduction_pct"] for s in summary.values()])
        avg_b_reduction = np.mean([s["plan_b_reduction_pct"] for s in summary.values()])
        avg_ab_iou = np.mean([s["ab_iou"] for s in summary.values()])
        avg_a_time = np.mean([s["plan_a_time"] for s in summary.values()])
        avg_b_time = np.mean([s["plan_b_time"] for s in summary.values()])

        print(f"\n[sam] Summary:")
        print(f"  Pages: {len(summary)}")
        print(f"  Plan A avg reduction: {avg_a_reduction:.1f}%")
        print(f"  Plan B avg reduction: {avg_b_reduction:.1f}%")
        print(f"  A/B avg IoU: {avg_ab_iou:.3f}")
        print(f"  Plan A avg time: {avg_a_time:.3f}s/page")
        print(f"  Plan B avg time: {avg_b_time:.3f}s/page")
        print(f"  Output: {OUT_DIR}")

    print("\n[sam] Done.")


if __name__ == "__main__":
    main()