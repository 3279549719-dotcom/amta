"""对比 raw / 旧V1 / 新textink final 在 p29 左上角黑发区的全分辨率裁切。"""
from pathlib import Path
from PIL import Image

ROOT = Path(r"E:\manga translator agent")
SRC = Path(r"D:\我的汉化\汉化作品\东方\月天新地_单页")
WORK = ROOT/"workspace"/"touhou-getten-shinchi"
V1 = ROOT/"output"/"inpaint-compare"/"V1_current"
OUT = ROOT/"output"/"inpaint-pixel-check"

page = 29
# 左上角黑发+旁白区域（放大）
x1,y1,x2,y2 = 0, 200, 280, 500

raw = Image.open(SRC/f"{page}.jpg").convert("RGB").crop((x1,y1,x2,y2))
old = Image.open(V1/f"page_{page}_final.png").convert("RGB").crop((x1,y1,x2,y2))
new = Image.open(WORK/"artifacts"/"final"/f"page_{page}_final.png").convert("RGB").crop((x1,y1,x2,y2))

scale = 2
def big(im): return im.resize((im.width*scale, im.height*scale), Image.LANCZOS)
raw, old, new = big(raw), big(old), big(new)

gap = 12
w = raw.width*3 + gap*2
h = raw.height
cv = Image.new("RGB", (w,h), (255,0,0))
cx = 0
for im in [raw, old, new]:
    cv.paste(im,(cx,0)); cx += im.width + gap
outp = OUT/"p29_final_hair_compare.png"
cv.save(outp)
print(outp, cv.size)
