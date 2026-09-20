"""可视化 p29 r00 的 textink mask：看 dilate=7 到底罩了哪些像素。"""
from __future__ import annotations
import sys, json
from pathlib import Path
ROOT = Path(r"E:\manga translator agent"); sys.path.insert(0, str(ROOT/"src"))
import numpy as np, cv2
from PIL import Image
from amta.inpaint.inpaint_station import _build_textink_mask

SRC = Path(r"D:\我的汉化\汉化作品\东方\月天新地_单页")
WORK = ROOT/"workspace"/"touhou-getten-shinchi"
ART = WORK/"artifacts"
OUT = ROOT/"output"/"inpaint-pixel-check"

page = 29
det = json.loads((ART/"detection"/f"page_{page}.json").read_text(encoding="utf-8"))
tr = json.loads((ART/"translation"/f"page_{page}.json").read_text(encoding="utf-8"))
keep = {rid for rid,d in tr.get("translations",{}).items() if d and d.strip()}
bm = {b["region_id"]: tuple(b["bbox"]) for b in det["blocks"]}
boxes = [bm[r] for r in keep if r in bm]

raw = Image.open(SRC/f"{page}.jpg").convert("RGB")

# 试不同 dilate
for dil in [2, 5, 7]:
    m = _build_textink_mask(raw, boxes, dilate=dil)
    m_arr = np.array(m)
    # 裁 r00 区域
    x1,y1,x2,y2 = 0,4,269,495
    crop_m = m_arr[y1:y2, x1:x2]
    crop_raw = np.array(raw)[y1:y2, x1:x2]
    # 叠加：mask=红
    overlay = crop_raw.copy()
    overlay[crop_m>128] = [255,0,0]
    side = np.hstack([crop_raw, overlay])
    Image.fromarray(side).save(OUT/f"p29_r00_mask_dil{dil}.png")
    print(f"dil={dil}: mask覆盖率 {(crop_m>128).mean()*100:.1f}%")
