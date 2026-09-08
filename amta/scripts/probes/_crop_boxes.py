"""裁剪9个滤除框的原图区域，保存为对比图。"""
from PIL import Image
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
OUT_DIR = r"E:\manga translator agent\amta\workspace\_rule_filter_probe"
os.makedirs(OUT_DIR, exist_ok=True)

print("=== 裁剪9个滤除框的原图区域 ===")
for page, rid, rule, page_num in TARGETS:
    img_path = os.path.join(IMG_DIR, f"{page_num}.jpg")
    det_path = os.path.join(DET_DIR, f"{page}.json")
    
    if not os.path.exists(img_path):
        print(f"  {page} {rid}: 原图不存在 {img_path}")
        continue
    if not os.path.exists(det_path):
        print(f"  {page} {rid}: detection不存在")
        continue
    
    det = json.load(open(det_path, encoding="utf-8"))
    block = next((b for b in det["blocks"] if b["region_id"] == rid), None)
    if not block:
        print(f"  {page} {rid}: detection中无此框")
        continue
    
    bbox = block["bbox"]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    w, h = x2 - x1, y2 - y1
    conf = block.get("confidence", 0)
    btype = block.get("bubble_type", "?")
    
    img = Image.open(img_path)
    # 扩大一点裁剪范围，加padding
    pad = 20
    cx1 = max(0, x1 - pad)
    cy1 = max(0, y1 - pad)
    cx2 = min(img.width, x2 + pad)
    cy2 = min(img.height, y2 + pad)
    crop = img.crop((cx1, cy1, cx2, cy2))
    
    out_name = f"{page}_{rid}_{rule}_conf{conf:.3f}_{w}x{h}.png"
    out_path = os.path.join(OUT_DIR, out_name)
    crop.save(out_path)
    
    aspect = max(w/h, h/w)
    print(f"  {page} {rid}: {w}x{h} aspect={aspect:.1f} conf={conf:.3f} type={btype} rule={rule}")
    print(f"    已保存: {out_name}")

print(f"\n裁剪完成，输出目录: {OUT_DIR}")
