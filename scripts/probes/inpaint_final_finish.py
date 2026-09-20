"""补跑缺失的 final 对比：p21 V4 + p29 全部。"""
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
ART = WORK / "artifacts"
OUT = ROOT / "output" / "inpaint-compare"

VARIANTS = {
    "V1_current": dict(mask="solid", feather=21, maxw=1024),
    "V2_textink_lr": dict(mask="textink", feather=5, maxw=1024),
    "V3_solid_hr": dict(mask="solid", feather=21, maxw=99999),
    "V4_textink_hr": dict(mask="textink", feather=5, maxw=99999),
}
# 只跑缺的
TODO = {
    29: ["V3_solid_hr", "V4_textink_hr"],
}


def load_boxes(page):
    det = json.loads((ART / "detection" / f"page_{page}.json").read_text(encoding="utf-8"))
    tr = json.loads((ART / "translation" / f"page_{page}.json").read_text(encoding="utf-8"))
    keep = {rid for rid, d in tr.get("translations", {}).items() if d and d.strip()}
    bm = {b["region_id"]: tuple(b["bbox"]) for b in det["blocks"]}
    return [bm[rid] for rid in keep if rid in bm]


def mask_solid(img, boxes, pad=4):
    w, h = img.size
    m = np.zeros((h, w), dtype=np.uint8)
    for (x1, y1, x2, y2) in boxes:
        x1 = max(0, int(x1 - pad)); y1 = max(0, int(y1 - pad))
        x2 = min(w, int(x2 + pad)); y2 = min(h, int(y2 + pad))
        m[y1:y2, x1:x2] = 255
    return Image.fromarray(m)


def mask_textink(img, boxes, thr=16, dilate=5):
    g = np.array(img.convert("L"))
    h, w = g.shape
    m = np.zeros((h, w), dtype=np.uint8)
    kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate * 2 + 1, dilate * 2 + 1))
    kc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    for (x1, y1, x2, y2) in boxes:
        x1 = max(0, int(x1)); y1 = max(0, int(y1))
        x2 = min(w, int(x2)); y2 = min(h, int(y2))
        crop = g[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        bg = cv2.medianBlur(crop, 15).astype(np.int16)
        diff = np.abs(crop.astype(np.int16) - bg)
        ink = (diff > thr).astype(np.uint8) * 255
        ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kc, iterations=2)
        ink = cv2.dilate(ink, kd, iterations=1)
        m[y1:y2, x1:x2] = np.maximum(m[y1:y2, x1:x2], ink)
    return Image.fromarray(m)


def infer(model, image, mask, feather, max_infer_width):
    device = model.device
    ow, oh = image.size
    scale = 1.0
    ii, im = image, mask
    if ow > max_infer_width:
        scale = max_infer_width / ow
        nw, nh = max_infer_width, max(1, int(oh * scale))
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


def main():
    from amta.inpaint.local_lama_inpainter import _LamaMangaModel
    from amta.typeset.typeset_station import run as typeset_run

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = _LamaMangaModel(device=torch.device(device))

    for page, vnames in TODO.items():
        raw = Image.open(SRC / f"{page}.jpg").convert("RGB")
        boxes = load_boxes(page)
        det_path = ART / "detection" / f"page_{page}.json"
        trans_path = ART / "translation" / f"page_{page}.json"
        canon_path = ART / "canon" / f"page_{page}.json"
        for vname in vnames:
            cfg = VARIANTS[vname]
            vdir = OUT / vname
            vdir.mkdir(exist_ok=True)
            mask = mask_solid(raw, boxes) if cfg["mask"] == "solid" else mask_textink(raw, boxes)
            clean = infer(model, raw, mask, cfg["feather"], cfg["maxw"])
            clean_path = vdir / f"page_{page}_clean.png"
            clean.save(clean_path)
            typeset_run(
                work_id="exp", canon_path=canon_path, trans_path=trans_path,
                det_path=det_path, clean_path=clean_path,
                out_path=vdir / f"page_{page}_typeset.json",
                final_path=vdir / f"page_{page}_final.png",
            )
            print(f"  p{page} {vname} done", flush=True)


if __name__ == "__main__":
    main()
