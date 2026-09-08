"""在原图完整页面上画出9个滤除框，标注ID和规则，方便肉眼判断。"""
from PIL import Image, ImageDraw, ImageFont
import os, json

# 9个滤除框
TARGETS = [
    ("page_2", "t04", "pure_punct", 2),
    ("page_6", "t08", "extreme_aspect", 6),
    ("page_13", "r01", "extreme_aspect", 13),
    ("page_16", "r03", "edge_box", 16),
    ("page_20", "r00", "edge_box", 20),
    ("page_22", "r08", "edge_box", 22),
    ("page_31", "t08", "extreme_aspect", 31),
    ("page_33", "r01", "extreme_aspect", 33),
    ("page_41", "r00", "extreme_aspect", 41),
]

IMG_DIR = r"D:\我的汉化\汉化作品\东方\单翼停留之地"
DET_DIR = r"E:\manga translator agent\amta\workspace\touhou-tiling-e2e\artifacts\detection"
OUT_DIR = r"E:\manga translator agent\amta\workspace\_rule_filter_probe\annotated"
os.makedirs(OUT_DIR, exist_ok=True)

# 颜色：误伤=红，真杂质=绿，边界=黄
JUDGMENT = {
    ("page_2", "t04"): ("真杂质", (0, 255, 0)),
    ("page_6", "t08"): ("真杂质", (0, 255, 0)),
    ("page_13", "r01"): ("误伤", (255, 0, 0)),
    ("page_16", "r03"): ("误伤", (255, 0, 0)),
    ("page_20", "r00"): ("误伤", (255, 0, 0)),
    ("page_22", "r08"): ("误伤", (255, 0, 0)),
    ("page_31", "t08"): ("边界", (255, 200, 0)),
    ("page_33", "r01"): ("误伤", (255, 0, 0)),
    ("page_41", "r00"): ("误伤", (255, 0, 0)),
}

print("=== 生成带标注的完整页面 ===")

# 按页面分组
pages = {}
for page, rid, rule, page_num in TARGETS:
    pages.setdefault(page_num, []).append((page, rid, rule))

for page_num, boxes in sorted(pages.items()):
    img_path = os.path.join(IMG_DIR, f"{page_num}.jpg")
    if not os.path.exists(img_path):
        print(f"  p{page_num}: 原图不存在")
        continue
    
    img = Image.open(img_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # 尝试加载字体
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 36)
        font_small = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 28)
    except:
        font = ImageFont.load_default()
        font_small = font
    
    for page, rid, rule in boxes:
        det_path = os.path.join(DET_DIR, f"{page}.json")
        det = json.load(open(det_path, encoding="utf-8"))
        block = next((b for b in det["blocks"] if b["region_id"] == rid), None)
        if not block:
            continue
        
        bbox = [int(v) for v in block["bbox"]]
        x1, y1, x2, y2 = bbox
        conf = block.get("confidence", 0)
        judgment, color = JUDGMENT.get((page, rid), ("未知", (255, 255, 255)))
        
        # 画粗框
        line_w = 6
        draw.rectangle([x1-line_w, y1-line_w, x2+line_w, y2+line_w], outline=color, width=line_w)
        
        # 标注文字背景
        label = f"{rid} | {rule} | conf={conf:.3f} | {judgment}"
        # 计算文字大小
        bbox_text = draw.textbbox((0, 0), label, font=font_small)
        tw, th = bbox_text[2] - bbox_text[0], bbox_text[3] - bbox_text[1]
        
        # 标签放在框上方，如果上方空间不够就放框内
        label_y = y1 - th - 10
        if label_y < 10:
            label_y = y1 + 10
        label_x = max(10, x1)
        
        # 背景
        draw.rectangle([label_x - 5, label_y - 3, label_x + tw + 10, label_y + th + 6], fill=(0, 0, 0))
        draw.text((label_x, label_y), label, fill=color, font=font_small)
    
    # 页面标题
    title = f"Page {page_num} — 被rule_filter过滤的框"
    draw.rectangle([0, 0, img.width, 60], fill=(0, 0, 0))
    draw.text((20, 10), title, fill=(255, 255, 255), font=font)
    
    out_path = os.path.join(OUT_DIR, f"page_{page_num}_annotated.jpg")
    # 缩小一点保存，避免太大
    if img.width > 1500:
        ratio = 1500 / img.width
        img = img.resize((1500, int(img.height * ratio)), Image.LANCZOS)
    img.save(out_path, quality=85)
    print(f"  p{page_num}: 已保存 {os.path.basename(out_path)} ({len(boxes)}个框)")

print(f"\n完成，输出目录: {OUT_DIR}")
