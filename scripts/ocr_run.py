"""在 recall_gt.json 的 101 个 GT 框上跑指定 OCR 引擎。
引擎: local(本地 llama-server :8118) | dashscope(qwen-vl-ocr)
用法: python scripts/ocr_run.py --engine local|dashscope [--pages N]
"""
from __future__ import annotations
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "output" / "data"


def crop_regions(gt, page_paths, crop_dir):
    """从原图按 GT bbox 裁框。page_paths: {page_num(int): img_path}。返回 (crop_paths, meta)。"""
    if isinstance(gt, (str, Path)):
        gt = json.loads(Path(gt).read_text(encoding="utf-8"))
    crop_dir = Path(crop_dir); crop_dir.mkdir(parents=True, exist_ok=True)
    crops, meta = [], []
    for gkey, regions in gt["pages"].items():
        page_num = int(gkey.split("_")[1])
        src = page_paths.get(page_num)
        if src is None or not Path(src).exists():
            continue
        im = Image.open(src)
        for i, region in enumerate(regions):
            x0, y0, x1, y1 = (int(v) for v in region["bbox"])
            box = (max(0, x0 - 4), max(0, y0 - 4), min(im.width, x1 + 4), min(im.height, y1 + 4))
            fname = f"{gkey}_gt{i:02d}.png"
            crop = im.crop(box)
            p = crop_dir / fname
            crop.save(p)
            crops.append(str(p))
            meta.append({"page": page_num, "crop": str(p), "bbox": region["bbox"],
                         "content": region["content"], "type": region["type"]})
    return crops, meta
