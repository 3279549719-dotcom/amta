"""Q3 实验：两个未被过滤的杂质框在最终成品中的视觉污染效果。

实验对象:
  - p2 t04: 页面刻度线, OCR="...", conf=0.704, 被 pure_punct 过滤
  - p31 t08: 边缘装饰线, OCR="美術館は、", conf=0.725, 被 extreme_aspect(已移除)过滤

实验方法:
  1. 只对杂质框做 lama inpaint（其他框保持原图）
  2. 渲染模拟 LLM 翻译文本到杂质框位置
  3. 输出局部放大对比图（原图 / inpaint后 / 渲染后）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

# 确保 src 在 path 中
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from amta.inpaint.inpaint_station import _build_mask_image, _get_inpainter
from amta.typeset.typeset_render import render_item

# ---- 配置 ----
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT_DIR = ROOT / "workspace" / "exp-q3-garbled-box-visual"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
STROKE = 0

# 两个杂质框
CASES = [
    {
        "page": 2,
        "region_id": "t04",
        "bbox": [463, 2247, 519, 2494],
        "ocr_text": "...",
        "mock_translation": "...",  # 纯标点，LLM 原样输出
        "desc": "页面刻度线 (pure_punct)",
    },
    {
        "page": 31,
        "region_id": "t08",
        "bbox": [246, 1490, 287, 2109],
        "ocr_text": "美術館は、",
        "mock_translation": "美术馆是、",  # 模拟 LLM 直译
        "desc": "边缘装饰线 (extreme_aspect已移除)",
    },
]


def crop_with_pad(img: Image.Image, bbox: list, pad: int = 80) -> Image.Image:
    """围绕 bbox 裁剪局部图，带 padding。"""
    x1, y1, x2, y2 = [int(v) for v in bbox]
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    w, h = x2 - x1, y2 - y1
    half = max(w, h) // 2 + pad
    cx1 = max(0, cx - half)
    cy1 = max(0, cy - half)
    cx2 = min(img.width, cx + half)
    cy2 = min(img.height, cy + half)
    return img.crop((cx1, cy1, cx2, cy2))


def process_case(case: dict) -> dict:
    """处理单个杂质框，返回对比图路径。"""
    page = case["page"]
    rid = case["region_id"]
    bbox = case["bbox"]
    translation = case["mock_translation"]

    raw_path = RAW_DIR / f"{page}.jpg"
    raw_img = Image.open(raw_path).convert("RGB")

    # 1. 原图局部
    raw_crop = crop_with_pad(raw_img, bbox)
    raw_crop.save(OUT_DIR / f"page_{page}_{rid}_01_raw.png")

    # 2. 只对这个框做 inpaint
    print(f"[page {page} {rid}] loading lama inpainter...")
    inpainter = _get_inpainter()
    mask_img = _build_mask_image(raw_img, [bbox], pad=4, refine=False)
    inpainted = inpainter.inpaint(raw_img, mask_img)
    if inpainted.size != raw_img.size:
        inpainted = inpainted.resize(raw_img.size, Image.LANCZOS)

    inpaint_crop = crop_with_pad(inpainted, bbox)
    inpaint_crop.save(OUT_DIR / f"page_{page}_{rid}_02_inpainted.png")

    # 3. 渲染模拟翻译文本
    final_img = inpainted.copy()
    meta = render_item(final_img, translation, FONT_PATH, bbox, stroke=STROKE)
    print(f"[page {page} {rid}] rendered: direction={meta['layout_direction']}, "
          f"font_size={meta['font_size']}, lines={meta['lines']}")

    final_crop = crop_with_pad(final_img, bbox)
    final_crop.save(OUT_DIR / f"page_{page}_{rid}_03_final.png")

    # 4. 保存全图（标注杂质框位置）
    from PIL import ImageDraw
    full_img = final_img.copy()
    draw = ImageDraw.Draw(full_img)
    x1, y1, x2, y2 = [int(v) for v in bbox]
    draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=4)
    full_img.save(OUT_DIR / f"page_{page}_{rid}_04_full_annotated.png")

    return {
        "page": page,
        "region_id": rid,
        "desc": case["desc"],
        "ocr_text": case["ocr_text"],
        "mock_translation": translation,
        "bbox": bbox,
        "render_meta": meta,
        "outputs": {
            "raw": str(OUT_DIR / f"page_{page}_{rid}_01_raw.png"),
            "inpainted": str(OUT_DIR / f"page_{page}_{rid}_02_inpainted.png"),
            "final": str(OUT_DIR / f"page_{page}_{rid}_03_final.png"),
            "full_annotated": str(OUT_DIR / f"page_{page}_{rid}_04_full_annotated.png"),
        },
    }


def main():
    results = []
    for case in CASES:
        print(f"\n=== Processing page {case['page']} {case['region_id']} ===")
        print(f"  desc: {case['desc']}")
        print(f"  bbox: {case['bbox']}")
        print(f"  OCR:  {case['ocr_text']}")
        print(f"  mock translation: {case['mock_translation']}")
        result = process_case(case)
        results.append(result)

    # 汇总
    print("\n" + "=" * 60)
    print("实验完成。输出目录:", OUT_DIR)
    print("=" * 60)
    for r in results:
        print(f"\npage {r['page']} {r['region_id']} ({r['desc']})")
        print(f"  OCR: {r['ocr_text']} → 翻译: {r['mock_translation']}")
        print(f"  渲染: direction={r['render_meta']['layout_direction']}, "
              f"font_size={r['render_meta']['font_size']}")
        for name, path in r["outputs"].items():
            print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
