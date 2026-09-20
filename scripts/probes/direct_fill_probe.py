"""探针：直接用局部 median 色填文字像素（不跑 LaMa），验证是否同时保住黑发颜色+细节。"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(r"E:\manga translator agent"); sys.path.insert(0, str(ROOT/"src"))
import json, cv2, numpy as np
from PIL import Image

SRC = Path(r"D:\我的汉化\汉化作品\东方\月天新地_单页")
WORK = ROOT/"workspace"/"touhou-getten-shinchi"
ART = WORK/"artifacts"
OUT = ROOT/"output"/"inpaint-direct"
OUT.mkdir(exist_ok=True)


def boxes_for(page):
    det = json.loads((ART/"detection"/f"page_{page}.json").read_text(encoding="utf-8"))
    tr = json.loads((ART/"translation"/f"page_{page}.json").read_text(encoding="utf-8"))
    keep = {rid for rid,d in tr.get("translations",{}).items() if d and d.strip()}
    bm = {b["region_id"]: tuple(b["bbox"]) for b in det["blocks"]}
    return [bm[r] for r in keep if r in bm], det["blocks"]


def direct_fill(img, bboxes, bg_ksize=15, thr=8, dilate=7):
    """直接用局部 median 色填文字像素，不跑模型。"""
    arr = np.array(img.convert("RGB")).copy()
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate*2+1, dilate*2+1))
    kc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
    for (x1,y1,x2,y2) in bboxes:
        x1=max(0,int(x1)); y1=max(0,int(y1)); x2=min(w,int(x2)); y2=min(h,int(y2))
        crop_gray = gray[y1:y2, x1:x2]
        crop_rgb = arr[y1:y2, x1:x2]
        if crop_gray.size==0: continue
        # 局部背景：median blur 估计
        bg_gray = cv2.medianBlur(crop_gray, bg_ksize).astype(np.int16)
        diff = np.abs(crop_gray.astype(np.int16)-bg_gray)
        ink = (diff > thr).astype(np.uint8)
        ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kc, iterations=2)
        ink = cv2.dilate(ink, kd, iterations=1)
        # 用 median 背景色填文字像素（按通道分别填）
        bg_rgb = cv2.medianBlur(crop_rgb, bg_ksize)
        mask_bool = ink > 0
        crop_rgb[mask_bool] = bg_rgb[mask_bool]
    return Image.fromarray(arr)


def main():
    for page, rids in [(29, ["r00"]), (16, ["r04"]), (21, ["r01"])]:
        raw = Image.open(SRC/f"{page}.jpg").convert("RGB")
        boxes, blocks = boxes_for(page)
        res = direct_fill(raw, boxes)
        res.save(OUT/f"page_{page}_direct.png")
        # 裁关键区域
        for rid in rids:
            b = next(x for x in blocks if x["region_id"]==rid)
            bx1,by1,bx2,by2=[int(v) for v in b["bbox"]]
            pad=15
            c = res.crop((max(0,bx1-pad),max(0,by1-pad),min(raw.width,bx2+pad),min(raw.height,by2+pad)))
            rc = raw.crop((max(0,bx1-pad),max(0,by1-pad),min(raw.width,bx2+pad),min(raw.height,by2+pad)))
            # 并排
            gap=12
            w=rc.width*2+gap; h=rc.height
            cv=Image.new("RGB",(w,h),(255,0,0))
            cv.paste(rc,(0,0)); cv.paste(c,(rc.width+gap,0))
            if cv.width>900:
                sc=900/cv.width; cv=cv.resize((900,int(cv.height*sc)),Image.LANCZOS)
            cv.save(OUT/f"p{page}_{rid}_raw_vs_direct.png")
        print(f"p{page} done", flush=True)


if __name__=="__main__":
    main()
