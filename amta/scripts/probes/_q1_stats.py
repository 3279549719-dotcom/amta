"""临时统计：基于已生成的 detection 数据，统计瓦片化新增框和 text_bubble 像素特征。"""
import json
from pathlib import Path
from PIL import Image
import numpy as np

RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
DET_DIR = Path("workspace/exp-q1-tiling-garbled/artifacts/detection")

tiled_boxes = []
total_boxes = 0
text_bubble_stats = []

for f in sorted(DET_DIR.glob("page_*.json")):
    doc = json.loads(f.read_text(encoding="utf-8"))
    page = int(doc["page"].split("_")[1])
    raw_path = RAW_DIR / f"{page}.jpg"
    img = None
    if raw_path.exists():
        img = Image.open(raw_path).convert("L")  # 灰度

    for b in doc["blocks"]:
        total_boxes += 1
        is_tiled = "rtdetr-v2-tiled" in b.get("source_engines", [])
        if is_tiled:
            tiled_boxes.append({
                "page": page, "rid": b["region_id"],
                "conf": b.get("confidence", 0), "type": b.get("bubble_type", ""),
            })

        # 统计 text_bubble 框的像素特征
        if b.get("bubble_type") == "text_bubble" and img is not None:
            x1, y1, x2, y2 = [int(v) for v in b["bbox"]]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(img.width, x2), min(img.height, y2)
            if x2 > x1 and y2 > y1:
                crop = np.array(img.crop((x1, y1, x2, y2)))
                white_ratio = float(np.mean(crop > 240))
                variance = float(np.var(crop))
                mean_bright = float(np.mean(crop))
                text_bubble_stats.append({
                    "page": page, "rid": b["region_id"],
                    "white_ratio": white_ratio, "variance": variance,
                    "mean_bright": mean_bright, "is_tiled": is_tiled,
                })

print(f"已处理页数: {len(list(DET_DIR.glob('page_*.json')))}")
print(f"总框数: {total_boxes}")
print(f"瓦片化新增框: {len(tiled_boxes)}")
print(f"分布页数: {sorted(set(b['page'] for b in tiled_boxes))}")
for b in tiled_boxes:
    print(f"  p{b['page']} {b['rid']} conf={b['conf']:.3f} type={b['type']}")

print(f"\n=== text_bubble 像素特征统计（{len(text_bubble_stats)} 个框）===")
if text_bubble_stats:
    white_ratios = [s["white_ratio"] for s in text_bubble_stats]
    variances = [s["variance"] for s in text_bubble_stats]
    print(f"白色占比: min={min(white_ratios):.3f}, max={max(white_ratios):.3f}, mean={np.mean(white_ratios):.3f}")
    print(f"像素方差: min={min(variances):.1f}, max={max(variances):.1f}, mean={np.mean(variances):.1f}")

    # 判定"假白底"：白色占比 < 0.7 或方差 > 1000
    fake_white = [s for s in text_bubble_stats if s["white_ratio"] < 0.7 or s["variance"] > 1000]
    print(f"\n假·text_bubble（白色占比<70% 或 方差>1000）: {len(fake_white)} 个")
    for s in fake_white:
        print(f"  p{s['page']} {s['rid']} white={s['white_ratio']:.3f} var={s['variance']:.1f} tiled={s['is_tiled']}")
