"""A/B：实心矩形 mask vs 文字墨迹 mask，在 p29 上对比，验证哪个保住原画。

不改动产品代码，只在探针里实验。
输出到 output/inpaint-ab/page_29/：
  - A_solid.png      现状策略全页
  - B_textink.png    文字墨迹策略全页
  - r00_*.png        r00 框区域 A|B 并排
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"E:\manga translator agent")
sys.path.insert(0, str(ROOT / "src"))

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw

WORK = ROOT / "workspace" / "touhou-getten-shinchi"
SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\月天新地_单页")
OUT = ROOT / "output" / "inpaint-ab" / "page_29"
OUT.mkdir(parents=True, exist_ok=True)

PAD = 4


def build_solid_mask(img: Image.Image, bboxes) -> Image.Image:
    w, h = img.size
    m = np.zeros((h, w), dtype=np.uint8)
    for (x1, y1, x2, y2) in bboxes:
        x1 = max(0, int(x1 - PAD)); y1 = max(0, int(y1 - PAD))
        x2 = min(w, int(x2 + PAD)); y2 = min(h, int(y2 + PAD))
        m[y1:y2, x1:x2] = 255
    return Image.fromarray(m)


def build_textink_mask(img: Image.Image, bboxes, dilate=2) -> Image.Image:
    """在每个 bbox 内：找出与局部背景反差大的像素（=文字墨迹），只 mask 这些。"""
    g = np.array(img.convert("L"))
    h, w = g.shape
    m = np.zeros((h, w), dtype=np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate * 2 + 1, dilate * 2 + 1))
    for (x1, y1, x2, y2) in bboxes:
        x1 = max(0, int(x1)); y1 = max(0, int(y1))
        x2 = min(w, int(x2)); y2 = min(h, int(y2))
        crop = g[y1:y2, x1:x2].astype(np.float32)
        if crop.size == 0:
            continue
        # 局部背景 = 大核中位数近似（用 median blur 模拟）
        bg = cv2.medianBlur(crop.astype(np.uint8), 15)
        diff = np.abs(crop.astype(np.int16) - bg.astype(np.int16))
        # 反差 > 阈值 视为墨迹
        ink = (diff > 40).astype(np.uint8) * 255
        ink = cv2.dilate(ink, k, iterations=1)
        m[y1:y2, x1:x2] = np.maximum(m[y1:y2, x1:x2], ink)
    return Image.fromarray(m)


def main() -> None:
    from amta.inpaint.local_lama_inpainter import LocalLamaInpainter

    page = 29
    raw = Image.open(SRC_DIR / f"{page}.jpg").convert("RGB")
    det = json.loads((WORK / "artifacts" / "detection" / f"page_{page}.json").read_text(encoding="utf-8"))
    trans = json.loads((WORK / "artifacts" / "translation" / f"page_{page}.json").read_text(encoding="utf-8"))
    keep = {rid for rid, d in trans.get("translations", {}).items() if d and d.strip()}
    bboxes = [tuple(b["bbox"]) for b in det["blocks"] if b["region_id"] in keep]
    print(f"page={page} inpaint boxes={len(bboxes)}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={device}")
    inp = LocalLamaInpainter(device=device, model_type="lama-manga")

    for name, builder in [("A_solid", build_solid_mask), ("B_textink", build_textink_mask)]:
        mask = builder(raw, bboxes)
        mask.save(OUT / f"mask_{name}.png")
        result, dt = inp.inpaint_timed(raw, mask)
        result.save(OUT / f"{name}.png")
        print(f"  {name}: {dt:.1f}s")

    # r00 区域并排
    r00 = [b["bbox"] for b in det["blocks"] if b["region_id"] == "r00"][0]
    x1, y1, x2, y2 = [int(v) for v in r00]
    c1, r1, c2, r2 = max(0, x1 - 20), max(0, y1 - 20), x2 + 20, y2 + 20
    a = Image.open(OUT / "A_solid.png").crop((c1, r1, c2, r2))
    b = Image.open(OUT / "B_textink.png").crop((c1, r1, c2, r2))
    combo = Image.new("RGB", (a.width + b.width + 10, a.height), (255, 0, 0))
    combo.paste(a, (0, 0)); combo.paste(b, (a.width + 10, 0))
    if combo.width > 1000:
        sc = 1000 / combo.width
        combo = combo.resize((1000, int(combo.height * sc)), Image.LANCZOS)
    combo.save(OUT / "r00_A_left_B_right.png")
    print(f"输出: {OUT}")


if __name__ == "__main__":
    main()
