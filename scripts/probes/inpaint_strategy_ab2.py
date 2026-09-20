"""A/B v2：调优文字墨迹 mask + 可控羽化，在 p29 重灾区和 p16 白泡上对比。

自己写推理循环以控制 feather（产品代码里硬编码 21）。
输出到 output/inpaint-ab2/：
  - tuned_textink_feather5 / feather21 全页 + r00 / 白泡裁切
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
OUT = ROOT / "output" / "inpaint-ab2"
OUT.mkdir(parents=True, exist_ok=True)

MAX_W = 1024


def build_textink(img: Image.Image, bboxes, thr=14, dilate=5) -> Image.Image:
    g = np.array(img.convert("L"))
    h, w = g.shape
    m = np.zeros((h, w), dtype=np.uint8)
    kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate * 2 + 1, dilate * 2 + 1))
    kc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    for (x1, y1, x2, y2) in bboxes:
        x1 = max(0, int(x1)); y1 = max(0, int(y1))
        x2 = min(w, int(x2)); y2 = min(h, int(y2))
        crop = g[y1:y2, x1:x2].astype(np.float32)
        if crop.size == 0:
            continue
        bg = cv2.medianBlur(crop.astype(np.uint8), 15).astype(np.int16)
        diff = np.abs(crop.astype(np.int16) - bg)
        ink = (diff > thr).astype(np.uint8) * 255
        ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kc, iterations=2)
        ink = cv2.dilate(ink, kd, iterations=1)
        m[y1:y2, x1:x2] = np.maximum(m[y1:y2, x1:x2], ink)
    return Image.fromarray(m)


def build_solid(img: Image.Image, bboxes, pad=4) -> Image.Image:
    w, h = img.size
    m = np.zeros((h, w), dtype=np.uint8)
    for (x1, y1, x2, y2) in bboxes:
        x1 = max(0, int(x1 - pad)); y1 = max(0, int(y1 - pad))
        x2 = min(w, int(x2 + pad)); y2 = min(h, int(y2 + pad))
        m[y1:y2, x1:x2] = 255
    return Image.fromarray(m)


def infer(model, image: Image.Image, mask: Image.Image, feather: int) -> Image.Image:
    """复制 _LamaMangaModel.__call__，但 feather 可控。"""
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
    # pad to 8
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
    # blend with controlled feather
    om = (np.array(mask).astype(np.float32) > 0).astype(np.float32)
    k = feather if feather % 2 == 1 else feather + 1
    blur = cv2.GaussianBlur(om, (k, k), 0)
    mt = torch.from_numpy(blur).unsqueeze(0).unsqueeze(0).to(device)
    orig = np.array(image).astype(np.float32) / 255.0
    orig_t = torch.from_numpy(orig).permute(2, 0, 1).unsqueeze(0).to(device)
    res = orig_t * (1 - mt) + out * mt
    res = (res[0].permute(1, 2, 0).cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
    return Image.fromarray(res)


def boxes_for(page: int):
    det = json.loads((WORK / "artifacts" / "detection" / f"page_{page}.json").read_text(encoding="utf-8"))
    tr = json.loads((WORK / "artifacts" / "translation" / f"page_{page}.json").read_text(encoding="utf-8"))
    keep = {rid for rid, d in tr.get("translations", {}).items() if d and d.strip()}
    return [tuple(b["bbox"]) for b in det["blocks"] if b["region_id"] in keep], det["blocks"]


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
    print("loading model on", device)
    model = _LamaMangaModel(device=torch.device(device))

    for page, rids in [(21, ["r01", "r03"]), (29, ["r00", "r05"]), (16, ["r04"])]:
        raw = Image.open(SRC / f"{page}.jpg").convert("RGB")
        boxes, blocks = boxes_for(page)
        for label, mk, feather in [
            ("solid_f21", build_solid, 21),
            ("textink_aggr_f5", build_textink, 5),
        ]:
            mask = mk(raw, boxes)
            res = infer(model, raw, mask, feather)
            res.save(OUT / f"p{page}_{label}.png")
            for rid in rids:
                save_crop(res, blocks, rid, OUT / f"p{page}_{label}_{rid}.png")
            print(f"p{page} {label} done")


if __name__ == "__main__":
    main()
