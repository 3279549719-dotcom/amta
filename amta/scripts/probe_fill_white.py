"""最小验证: text_bubble 涂白, text_free 红框标注, 5页前后对比。

验证三点:
1. 框内字是否完全被覆盖(无残字)
2. 有没有涂到框外(破坏气泡边缘/画面)
3. 检测框本身准不准(漏字/多框)

样本: page_10~page_14 (11.jpg~15.jpg)
输出: output/tmp/fill_white_probe/
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
ARTIFACTS_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "fill_white_probe"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGES = [
    {"page_idx": 10, "file": "11.jpg", "name": "page_10"},
    {"page_idx": 11, "file": "12.jpg", "name": "page_11"},
    {"page_idx": 12, "file": "13.jpg", "name": "page_12"},
    {"page_idx": 13, "file": "14.jpg", "name": "page_13"},
    {"page_idx": 14, "file": "15.jpg", "name": "page_14"},
]

COLOR_FREE_BOX = (255, 0, 0)  # 红框标注框外字
COLOR_FREE_LABEL = (255, 255, 255)


def process_page(page: dict) -> dict:
    """处理单页: text_bubble涂白, text_free红框标注。返回统计。"""
    raw_path = SRC_DIR / page["file"]
    det_path = ARTIFACTS_DIR / f"{page['name']}_detection.json"

    original = Image.open(raw_path).convert("RGB")
    w, h = original.size

    with open(det_path, "r", encoding="utf-8") as f:
        det = json.load(f)
    blocks = det["blocks"]
    bubble_boxes = [b for b in blocks if b.get("bubble_type") == "text_bubble"]
    free_boxes = [b for b in blocks if b.get("bubble_type") == "text_free"]

    # 涂白 text_bubble
    processed = original.copy()
    draw = ImageDraw.Draw(processed)
    for b in bubble_boxes:
        x1, y1, x2, y2 = [int(v) for v in b["bbox"]]
        draw.rectangle([x1, y1, x2, y2], fill=(255, 255, 255))

    # 红框标注 text_free (不处理)
    for i, b in enumerate(free_boxes):
        x1, y1, x2, y2 = [int(v) for v in b["bbox"]]
        draw.rectangle([x1, y1, x2, y2], outline=COLOR_FREE_BOX, width=4)
        draw.text((x1 + 6, y1 + 4), f"FREE#{i}", fill=COLOR_FREE_BOX)

    # 保存
    original.save(OUT_DIR / f"{page['name']}_original.png")
    processed.save(OUT_DIR / f"{page['name']}_processed.png")

    # 生成左右对比图
    target_h = 1400
    def resize(im):
        s = target_h / im.height
        return im.resize((int(im.width * s), target_h), Image.LANCZOS)

    orig_r = resize(original)
    proc_r = resize(processed)
    gap = 20
    canvas = Image.new("RGB", (orig_r.width * 2 + gap, target_h + 40), (240, 240, 240))
    d = ImageDraw.Draw(canvas)
    d.text((10, 8), "Original", fill=(0, 0, 0))
    d.text((orig_r.width + gap + 10, 8), "Processed (bubble=white, free=red box)", fill=(0, 0, 0))
    canvas.paste(orig_r, (0, 40))
    canvas.paste(proc_r, (orig_r.width + gap, 40))
    canvas.save(OUT_DIR / f"{page['name']}_comparison.png")

    # 统计: 检查涂白区域是否还有深色像素(残字)
    proc_arr = np.array(processed.convert("L"))
    residual_info = []
    for b in bubble_boxes:
        x1, y1, x2, y2 = [int(v) for v in b["bbox"]]
        region = proc_arr[y1:y2, x1:x2]
        dark_pixels = int(np.sum(region < 200))  # 非纯白像素
        total = region.size
        residual_info.append({
            "region_id": b.get("region_id", "?"),
            "bbox": [x1, y1, x2, y2],
            "dark_pixels_after": dark_pixels,
            "dark_ratio": round(dark_pixels / max(1, total), 4),
        })

    stats = {
        "page": page["name"],
        "file": page["file"],
        "image_size": [w, h],
        "n_bubble": len(bubble_boxes),
        "n_free": len(free_boxes),
        "residual_check": residual_info,
        "max_dark_ratio": max([r["dark_ratio"] for r in residual_info]) if residual_info else 0,
    }
    print(f"  {page['name']}: bubble={len(bubble_boxes)}, free={len(free_boxes)}, "
          f"max_dark_ratio={stats['max_dark_ratio']*100:.2f}%")
    return stats


def main():
    print(f"[fill_white_probe] Output: {OUT_DIR}")
    print(f"[fill_white_probe] Pages: {[p['name'] for p in PAGES]}")
    print()

    all_stats = []
    for page in PAGES:
        stats = process_page(page)
        all_stats.append(stats)

    with open(OUT_DIR / "summary.json", "w", encoding="utf-8") as f:
        json.dump(all_stats, f, ensure_ascii=False, indent=2)

    # 总体统计
    total_bubble = sum(s["n_bubble"] for s in all_stats)
    total_free = sum(s["n_free"] for s in all_stats)
    worst = max(all_stats, key=lambda s: s["max_dark_ratio"])
    print(f"\n[fill_white_probe] Total: bubble={total_bubble}, free={total_free}")
    print(f"[fill_white_probe] Worst page: {worst['page']} (max_dark_ratio={worst['max_dark_ratio']*100:.2f}%)")
    print("[fill_white_probe] Done.")


if __name__ == "__main__":
    main()
