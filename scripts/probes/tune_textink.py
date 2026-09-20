"""调优墨迹 mask：白泡无残影 + 黑发保住。只跑 p16/p29 关键页，HR。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"E:\manga translator agent")
sys.path.insert(0, str(ROOT / "src"))
import cv2, numpy as np, torch
from PIL import Image

WORK = ROOT / "workspace" / "touhou-getten-shinchi"
SRC = Path(r"D:\我的汉化\汉化作品\东方\月天新地_单页")
ART = WORK / "artifacts"
OUT = ROOT / "output" / "inpaint-tune"
OUT.mkdir(parents=True, exist_ok=True)


def boxes_for(page):
    det = json.loads((ART / "detection" / f"page_{page}.json").read_text(encoding="utf-8"))
    tr = json.loads((ART / "translation" / f"page_{page}.json").read_text(encoding="utf-8"))
    keep = {rid for rid, d in tr.get("translations", {}).items() if d and d.strip()}
    bm = {b["region_id"]: tuple(b["bbox"]) for b in det["blocks"]}
    return [bm[r] for r in keep if r in bm], det["blocks"]


def textink(img, boxes, thr, dilate):
    g = np.array(img.convert("L")); h, w = g.shape
    m = np.zeros((h, w), np.uint8)
    kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate*2+1, dilate*2+1))
    kc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    for (x1, y1, x2, y2) in boxes:
        x1=max(0,int(x1)); y1=max(0,int(y1)); x2=min(w,int(x2)); y2=min(h,int(y2))
        c = g[y1:y2, x1:x2]
        if c.size == 0: continue
        bg = cv2.medianBlur(c, 15).astype(np.int16)
        ink = (np.abs(c.astype(np.int16)-bg) > thr).astype(np.uint8)*255
        ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kc, iterations=2)
        ink = cv2.dilate(ink, kd, iterations=1)
        m[y1:y2, x1:x2] = np.maximum(m[y1:y2, x1:x2], ink)
    return Image.fromarray(m)


def infer(model, image, mask, feather=5):
    device = model.device
    ow, oh = image.size
    img_np = np.array(image).astype(np.float32)/255.0
    mask_np = (np.array(mask).astype(np.float32)>0).astype(np.float32)
    it = torch.from_numpy(img_np).permute(2,0,1).unsqueeze(0).to(device)
    mt = torch.from_numpy(mask_np).unsqueeze(0).unsqueeze(0).to(device)
    _,_,hh,ww = it.shape
    ph=(8-hh%8)%8; pw=(8-ww%8)%8
    if ph or pw:
        it=torch.nn.functional.pad(it,(0,pw,0,ph),mode='reflect')
        mt=torch.nn.functional.pad(mt,(0,pw,0,ph),mode='reflect')
    with torch.inference_mode(): out = model.model(it, mt)
    out = torch.sigmoid(out)[:,:,:oh,:ow]
    om = (np.array(mask).astype(np.float32)>0).astype(np.float32)
    k = feather if feather%2==1 else feather+1
    blur = cv2.GaussianBlur(om,(k,k),0)
    mt2 = torch.from_numpy(blur).unsqueeze(0).unsqueeze(0).to(device)
    ot = torch.from_numpy(np.array(image).astype(np.float32)/255.0).permute(2,0,1).unsqueeze(0).to(device)
    r = ot*(1-mt2)+out*mt2
    return Image.fromarray((r[0].permute(1,2,0).cpu().numpy()*255).clip(0,255).astype(np.uint8))


def crop(img, blocks, rid, path, pad=20):
    b = next(x for x in blocks if x["region_id"]==rid)
    x1,y1,x2,y2=[int(v) for v in b["bbox"]]
    c = img.crop((max(0,x1-pad),max(0,y1-pad),min(img.width,x2+pad),min(img.height,y2+pad)))
    if c.width>600:
        sc=600/c.width; c=c.resize((600,int(c.height*sc)),Image.LANCZOS)
    c.save(path)


def main():
    from amta.inpaint.local_lama_inpainter import _LamaMangaModel
    model = _LamaMangaModel(device=torch.device("cuda" if torch.cuda.is_available() else "cpu"))
    for thr, dilate, tag in [(10,7,"t10d7")]:
        for page, rids in [(16,["r04"]),(29,["r00"])]:
            raw = Image.open(SRC/f"{page}.jpg").convert("RGB")
            boxes, blocks = boxes_for(page)
            mask = textink(raw, boxes, thr, dilate)
            res = infer(model, raw, mask, 5)
            for rid in rids:
                crop(res, blocks, rid, OUT/f"p{page}_{rid}_{tag}.png")
            print(f"p{page} {tag} done", flush=True)


if __name__=="__main__":
    main()
