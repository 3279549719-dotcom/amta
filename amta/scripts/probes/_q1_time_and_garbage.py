"""快速统计：瓦片化的时间增量 + 杂质框OCR验证。"""
import json
import glob
from pathlib import Path

DET_DIR = Path(r"E:\manga translator agent\amta\workspace\exp-q1-tiling-garbled\artifacts\detection")
AUDIT_JSON = Path(r"E:\manga translator agent\amta\workspace\exp-q1-tiling-garbled\artifacts\q1_audit_summary.json")

# 1. 统计开瓦片的平均detect时间
print("=== 开瓦片的 detect 时间统计 ===")
times = []
for f in sorted(DET_DIR.glob("page_*_detection.json")):
    doc = json.loads(f.read_text(encoding="utf-8"))
    t = doc.get("elapsed_s", 0)
    times.append(t)
    print(f"  {doc['page']}: {t:.2f}s, n_boxes={doc['n_boxes']}, tiled_raw={doc['per_engine_boxes'].get('rtdetr-v2-tiled-raw', '?')}")

print(f"\n  页数: {len(times)}")
print(f"  平均: {sum(times)/len(times):.2f}s")
print(f"  最小: {min(times):.2f}s")
print(f"  最大: {max(times):.2f}s")

# 2. 无瓦片的时间（从B组实验结果）
print(f"\n=== 无瓦片（主链conf=0.3）的 detect 时间 ===")
print(f"  17页总耗时: 41.8s")
print(f"  平均每页: {41.8/17:.2f}s")

# 3. 时间增量
avg_tiled = sum(times)/len(times)
avg_no_tiled = 41.8/17
print(f"\n=== 时间增量 ===")
print(f"  开瓦片平均: {avg_tiled:.2f}s")
print(f"  无瓦片平均: {avg_no_tiled:.2f}s")
print(f"  绝对增量: {avg_tiled - avg_no_tiled:.2f}s/页")
print(f"  相对倍数: {avg_tiled/avg_no_tiled:.1f}x")

# 4. 瓦片新增框的OCR文本（判断杂质）
print(f"\n=== 瓦片新增框20个的详情 ===")
audit = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
for t in audit["tiled_new_boxes"]:
    print(f"  p{t['page']:2d} {t['region_id']}: conf={t['confidence']:.4f}, bbox={[int(x) for x in t['bbox']]}")
