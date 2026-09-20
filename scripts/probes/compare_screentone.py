"""对比 p29 旁白网点背景：raw vs 旧V1 vs 新textink，看网点被修成什么样。"""
from pathlib import Path
from PIL import Image

ROOT = Path(r"E:\manga translator agent")
SRC = Path(r"D:\我的汉化\汉化作品\东方\月天新地_单页")
WORK = ROOT/"workspace"/"touhou-getten-shinchi"
V1 = ROOT/"output"/"inpaint-compare"/"V1_current"
OUT = ROOT/"output"/"inpaint-pixel-check"

page = 29
# 旁白网点背景区（文字右侧/周围的网点，不含黑发）
x1,y1,x2,y2 = 100, 20, 270, 280

raw = Image.open(SRC/f"{page}.jpg").convert("RGB").crop((x1,y1,x2,y2))
old = Image.open(V1/f"page_{page}_clean.png").convert("RGB").crop((x1,y1,x2,y2))
new = Image.open(WORK/"artifacts"/"clean"/f"page_{page}_clean.png").convert("RGB").crop((x1,y1,x2,y2))

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
outp = OUT/"p29_screentone_compare.png"
cv.save(outp)
print(outp, cv.size)
