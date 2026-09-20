"""一次性探针：裁出 p31 r02 框看是什么。"""
from PIL import Image, ImageDraw

src = r"D:\我的汉化\汉化作品\东方\月天新地_单页\31.jpg"
img = Image.open(src).convert("RGB")
print("page size:", img.size)

# r02 bbox
bbox = [17, 183, 76, 650]
crop = img.crop(tuple(bbox))
# 放大3倍方便看
crop = crop.resize((crop.width * 3, crop.height * 3))
crop.save(r"workspace\touhou-getten-shinchi\_probe\p31_r02_crop.png")

# 整页标框
marked = img.copy()
d = ImageDraw.Draw(marked)
d.rectangle(bbox, outline="red", width=3)
marked.save(r"workspace\touhou-getten-shinchi\_probe\p31_marked.png")
print("saved")
