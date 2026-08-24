"""GT→detector 框对齐：评测裁剪用 detector 全尺寸可靠 bbox，比对基准用 GT 内容。

背景（ADR-011）：GT bbox 是 VLM 整页枚举的缩略坐标（x 缩 ~40% 宽），直接裁剪全空白；
评测锚点改为：裁剪用 detector 对齐框，比对用 GT 内容。
"""
from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image


def _content_overlap(a: str, b: str) -> float:
    """字符重合度（SequenceMatcher ratio），用于内容级对齐 GT 与 detector 文本。"""
    na, nb = a or "", b or ""
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def crop_regions(gt, page_paths, crop_dir, det_boxes=None):
    """从原图按 detector 可靠坐标裁框，用 GT 内容做比对基准。

    det_boxes: {page_num: [{bbox, text}]} — 来自 ocr_result.json 的 manga-ocr 全尺寸框；
    缺省时回退 GT bbox（仅测试用）。返回 (crop_paths, meta)，meta 含 {page, crop, bbox, content, type}。
    """
    if isinstance(gt, (str, Path)):
        gt = json.loads(Path(gt).read_text(encoding="utf-8"))
    crop_dir = Path(crop_dir)
    crop_dir.mkdir(parents=True, exist_ok=True)
    crops, meta = [], []
    for gkey, regions in gt["pages"].items():
        page_num = int(gkey.split("_")[1])
        src = page_paths.get(page_num)
        if src is None or not Path(src).exists():
            continue
        im = Image.open(src)
        dets = det_boxes.get(page_num, []) if det_boxes else []
        used = [False] * len(dets)
        for i, region in enumerate(regions):
            content = region["content"]
            best_j, best_score = -1, 0.6
            for j, d in enumerate(dets):
                if used[j] or not d.get("text"):
                    continue
                sc = _content_overlap(content, d["text"])
                if sc >= best_score:
                    best_score, best_j = sc, j
            if best_j >= 0:
                bbox = dets[best_j]["bbox"]
                used[best_j] = True
            else:
                bbox = region["bbox"]  # 无匹配框：回退 GT bbox（该条计入未检出）
            x0, y0, x1, y1 = (int(v) for v in bbox)
            box = (max(0, x0 - 4), max(0, y0 - 4), min(im.width, x1 + 4), min(im.height, y1 + 4))
            fname = f"{gkey}_gt{i:02d}.png"
            p = crop_dir / fname
            im.crop(box).save(p)
            crops.append(str(p))
            meta.append({"page": page_num, "crop": str(p), "bbox": bbox,
                         "content": content, "type": region["type"]})
    return crops, meta
