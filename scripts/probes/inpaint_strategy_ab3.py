"""A/B v3：按框分流的混合 mask。
- 框内均匀（白底泡/黑底泡/纯色说明框）→ 实心矩形，擦得干净
- 框内复杂（字叠线稿/网点）→ 墨迹 mask，保原画
- feather 统一用 5
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
from PIL import Image

WORK = ROOT / "workspace" / "touhou-getten-shinchi"
SRC = Path(r"D:\我的汉化\汉化作品\东方\月天新地_单页")
OUT = ROOT / "output" / "inpaint-ab3"
OUT.mkdir(parents=True, exist_ok=True)
MAX_W = 1024


def is_uniform(crop_gray: np.ndarray, tol: int = 28, frac_thresh: float = 0.72) -> bool:
    """框内是否为均匀背景：足够多像素落在中位数 ±tol 内。"""
    med = np.median(crop_gray)
    near = np.mean(np.abs(crop_gray.astype(np.int16) - med) <= tol)
    return near > frac_thresh


def build_hybrid(img: Image.Image, bboxes, pad=3, thr=16, dilate=5):
    g = np.array(img.convert("L"))
    h, w = g.shape
    m = np.zeros((h, w), dtype=np.uint8)
    kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate * 2 + 1, dilate * 2 + 1))
    kc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    stats = []
    for (x1, y1, x2, y2) in bboxes:
        x1 = max(0, int(x1)); y1 = max(0, int(y1))
        x2 = min(w, int(x2)); y2 = min(h, int(y2))
        crop = g[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        uniform = is_uniform(crop)
        stats.append(((x1, y1, x2, y2), uniform))
        if uniform:
            # 实心矩形，轻微内缩避免框外描边
            m[max(0, y1):min(h, y2), max(0, x1):min(w, x2)] = 255
        else:
            c = crop.astype(np.float32)
            bg = cv2.medianBlur(crop, 15).astype(np.int16)
            diff = np.abs(c.astype(np.int16) - bg)
            ink = (diff > thr).astype(np.uint8) * 255
            ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kc, iterations=2)
            ink = cv2.dilate(ink, kd, iterations=1)
            m[y1:y2, x1:x2] = np.maximum(m[y1:y2, x1:x2], ink)
    return Image.fromarray(m), stats


def build_solid(img, bboxes, pad=4):
    w, h = img.size
    m = np.zeros((h, w), dtype=np.uint8)
    for (x1, y1, x2, y2) in bboxes:
        x1 = max(0, int(x1 - pad)); y1 = max(0, int(y1 - pad))
        x2 = min(w, int(x2 + pad)); y2 = min(h, int(y2 + pad))
        m[y1:y2, x1:x2] = 255
    return Image.fromarray(m)


def infer(model, image, mask, feather=5):
    device = model.device
    ow, oh = image.size
    scale = 1.0
    ii, im = image, mask
    if ow > MAX_W:
        scale = MAX_W / ow
        nw, nh = MAX_W, max(1, int(oh * scale))
        ii = image.resize((nw, nh), Image.LANCZOS)
        im = mask.resize((nw, nh), Image.NEAREST)
    iw, ih = ii.size
    img_np = np.array(ii).astype(np.float32) / 255.0
    mask_np = (np.array(im).astype(np.float32) > 0).astype(np.float32)
    img_t = torch.from_numpy(img_np).permute(2, 0, 1).unsqueeze(0).to(device)
    mask_t = torch.from_numpy(mask_np).unsqueeze(0).unsqueeze(0).to(device)
    _, _, hh, ww = img_t.shape
    ph = (8 - hh % 8) % 8; pw = (8 - ww % 8) % 8
    if ph or pw:
        img_t = torch.nn.functional.pad(img_t, (0, pw, 0, ph), mode='reflect')
        mask_t = torch.nn.functional.pad(mask_t, (0, pw, 0, ph), mode='reflect')
    with torch.inference_mode():
        out = model.model(img_t, mask_t)
    out = torch.sigmoid(out)[:, :, :ih, :iw]
    if scale < 1.0:
        out = torch.nn.functional.interpolate(out, size=(oh, ow), mode="bilinear", align_corners=False)
    om = (np.array(mask).astype(np.float32) > 0).astype(np.float32)
    k = feather if feather % 2 == 1 else feather + 1
    blur = cv2.GaussianBlur(om, (k, k), 0)
    mt = torch.from_numpy(blur).unsqueeze(0).unsqueeze(0).to(device)
    orig = np.array(image).astype(np.float32) / 255.0
    orig_t = torch.from_numpy(orig).permute(2, 0, 1).unsqueeze(0).to(device)
    res = orig_t * (1 - mt) + out * mt
    res = (res[0].permute(1, 2, 0).cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
    return Image.fromarray(res)


def boxes_for(page):
    det = json.loads((WORK / "artifacts" / "detection" / f"page_{page}.json").read_text(encoding="utf-8"))
    tr = json.loads((WORK / "artifacts" / "translation" / f"page_{page}.json").read_text(encoding="utf-8"))
    keep = {rid for rid, d in tr.get("translations", {}).items() if d and d.strip()}
    bm = {b["region_id"]: tuple(b["bbox"]) for b in det["blocks"]}
    boxes = [bm[rid] for rid in keep if rid in bm]
    return boxes, det["blocks"]


def save_crop(img, blocks, rid, path, pad=25):
    b = next(x for x in blocks if x["region_id"] == rid)
    x1, y1, x2, y2 = [int(v) for v in b["bbox"]]
    c = img.crop((max(0, x1 - pad), max(0, y1 - pad), min(img.width, x2 + pad), min(img.height, y2 + pad)))
    if c.width > 700:
        sc = 700 / c.width
        c = c.resize((700, int(c.height * sc)), Image.LANCZOS)
    c.save(path)


def main():
    from amta.inpaint.local_lama_inpainter import _LamaMangaModel
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = _LamaMangaModel(device=torch.device(device))

    for page, rids in [(29, ["r00"]), (21, ["r01", "r03"]), (16, ["r04", "r00"])]:
        raw = Image.open(SRC / f"{page}.jpg").convert("RGB")
        boxes, blocks = boxes_for(page)
        hm, stats = build_hybrid(raw, boxes)
        hm.save(OUT / f"p{page}_mask_hybrid.png")
        res = infer(model, raw, hm, 5)
        res.save(OUT / f"p{page}_hybrid.png")
        for rid in rids:
            save_crop(res, blocks, rid, OUT / f"p{page}_hybrid_{rid}.png")
        # 打印分流结果
        for (bb, uni) in stats:
            print(f"  p{page} box{bb} uniform={uni}")
        print(f"p{page} done")


if __name__ == "__main__":
    main()
