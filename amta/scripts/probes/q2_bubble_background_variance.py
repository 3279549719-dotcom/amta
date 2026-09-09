"""统计 text_bubble 框内背景方差 — 验证"检测器标签能否代表背景均匀纯白"。

对每个 text_bubble 框，计算框内灰度像素的方差：
- 方差低 → 背景均匀（纯白/纯黑/纯灰），适合涂白
- 方差高 → 背景复杂（网点/渐变/纹理），涂白会翻车

同时统计 text_free 框作为对照。
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ANNOTATED_DIR = Path(r"E:\manga translator agent\amta\workspace\exp-q1-tiling-garbled\annotated")
DETECTION_DIR = Path(r"E:\manga translator agent\amta\workspace\exp-q1-tiling-garbled\artifacts\detection")

# 方差阈值：灰度方差 < 100 视为"背景均匀"，> 500 视为"背景复杂"
# 纯白背景方差接近 0，网点背景方差通常 > 1000
UNIFORM_THRESH = 100
COMPLEX_THRESH = 500


def page_num_from_name(name: str) -> int:
    """从 page_11_annotated.jpg 或 page_11_detection.json 提取页码。"""
    import re
    m = re.search(r"page_(\d+)", name)
    return int(m.group(1)) if m else -1


def calc_bbox_variance(gray: np.ndarray, bbox: list[float]) -> float:
    """计算 bbox 内灰度像素方差。bbox = [x1, y1, x2, y2]。"""
    h, w = gray.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return -1.0
    crop = gray[y1:y2, x1:x2]
    if crop.size == 0:
        return -1.0
    return float(np.var(crop))


def main():
    results = {"text_bubble": [], "text_free": []}
    pages_processed = 0

    for img_path in sorted(ANNOTATED_DIR.glob("page_*_annotated.jpg")):
        page_num = page_num_from_name(img_path.name)
        det_path = DETECTION_DIR / f"page_{page_num}_detection.json"
        if not det_path.exists():
            print(f"  skip page_{page_num}: no detection.json")
            continue

        with open(det_path, encoding="utf-8") as f:
            det = json.load(f)

        img = cv2.imread(str(img_path))
        if img is None:
            print(f"  skip page_{page_num}: cannot read image")
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        pages_processed += 1
        for block in det.get("blocks", []):
            btype = block.get("bubble_type", "unknown")
            if btype not in ("text_bubble", "text_free"):
                continue
            var = calc_bbox_variance(gray, block["bbox"])
            if var < 0:
                continue
            results[btype].append({
                "page": page_num,
                "rid": block.get("region_id", "?"),
                "variance": round(var, 1),
                "bbox": block["bbox"],
            })

    # 统计
    print(f"\n{'='*60}")
    print(f"处理页数: {pages_processed}")
    print(f"{'='*60}")

    for btype in ("text_bubble", "text_free"):
        boxes = results[btype]
        if not boxes:
            print(f"\n{btype}: 0 boxes")
            continue
        variances = [b["variance"] for b in boxes]
        n_uniform = sum(1 for v in variances if v < UNIFORM_THRESH)
        n_mid = sum(1 for v in variances if UNIFORM_THRESH <= v < COMPLEX_THRESH)
        n_complex = sum(1 for v in variances if v >= COMPLEX_THRESH)

        print(f"\n--- {btype} (共 {len(boxes)} 框) ---")
        print(f"  方差 < {UNIFORM_THRESH} (背景均匀): {n_uniform} ({n_uniform/len(boxes)*100:.1f}%)")
        print(f"  方差 {UNIFORM_THRESH}~{COMPLEX_THRESH} (中等):   {n_mid} ({n_mid/len(boxes)*100:.1f}%)")
        print(f"  方差 >= {COMPLEX_THRESH} (背景复杂): {n_complex} ({n_complex/len(boxes)*100:.1f}%)")
        print(f"  方差中位数: {np.median(variances):.1f}")
        print(f"  方差均值: {np.mean(variances):.1f}")
        print(f"  方差最大: {np.max(variances):.1f}")

        # 列出高方差的 text_bubble 框（证明"气泡但背景不均匀"）
        if btype == "text_bubble" and n_complex > 0:
            print(f"\n  高方差 text_bubble 框 (>= {COMPLEX_THRESH}, 前10个):")
            complex_boxes = sorted(boxes, key=lambda x: -x["variance"])[:10]
            for b in complex_boxes:
                print(f"    page_{b['page']} {b['rid']}: var={b['variance']}")

    # 核心结论
    print(f"\n{'='*60}")
    print("核心结论:")
    tb = results["text_bubble"]
    if tb:
        n_complex_tb = sum(1 for b in tb if b["variance"] >= COMPLEX_THRESH)
        print(f"  text_bubble 框中，背景复杂(方差>={COMPLEX_THRESH})的有 {n_complex_tb}/{len(tb)} ({n_complex_tb/len(tb)*100:.1f}%)")
        print(f"  → 如果这些框用涂白(fill_white)，会直接翻车(白色方块盖网点/纹理)")
        print(f"  → 证明: 检测器的 text_bubble 标签 ≠ 背景均匀纯白")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
