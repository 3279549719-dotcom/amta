"""对比全分辨率 V3 HR 的网点背景。"""
from pathlib import Path
from PIL import Image

ROOT = Path(r"E:\manga translator agent")
SRC = Path(r"D:\我的汉化\汉化作品\东方\月天新地_单页")
V1 = ROOT/"output"/"inpaint-compare"/"V1_current"
V3HR = ROOT/"output"/"inpaint-compare"/"V3_solid_hr"
OUT = ROOT/"output"/"inpaint-pixel-check"

page = 29
x1,y1,x2,y2 = 100, 20, 270, 280

raw = Image.open(SRC/f"{page}.jpg").convert("RGB").crop((x1,y1,x2,y2))
v1 = Image.open(V1/f"page_{page}_clean.png").convert("RGB").crop((x1,y1,x2,y2))
v3 = Image.open(V3HR/f"page_{page}_clean.png").convert("RGB").crop((x1,y1,x2,y2))

scale = 2
def big(im): return im.resize((im.width*scale, im.height*scale), Image.LANCZOS)
raw, v1, v3 = big(raw), big(v1), big(v3)

gap = 12
w = raw.width*3 + gap*2
h = raw.height
cv = Image.new("RGB", (w,h), (255,0,0))
cx = 0
for im in [raw, v1, v3]:
    cv.paste(im,(cx,0)); cx += im.width + gap
outp = OUT/"p29_screentone_hr.png"
cv.save(outp)
print(outp)
