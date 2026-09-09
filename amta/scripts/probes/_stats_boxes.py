"""统计全量检测框数量和conf分布"""
import json
from pathlib import Path

det_dir = Path("workspace/touhou-tiling-e2e/artifacts/detection")
all_boxes = []
for f in sorted(det_dir.glob("page_*.json")):
    data = json.loads(f.read_text(encoding="utf-8"))
    page = data["page"]
    for b in data["blocks"]:
        b["page"] = page
        all_boxes.append(b)

print(f"总框数: {len(all_boxes)}")
print(f"页数: {len(set(b['page'] for b in all_boxes))}")

confs = [b["confidence"] for b in all_boxes]
print(f"\nconf 分布:")
print(f"  min={min(confs):.4f}, max={max(confs):.4f}, avg={sum(confs)/len(confs):.4f}")
for lo, hi in [(0.7,0.75),(0.75,0.8),(0.8,0.85),(0.85,0.9),(0.9,0.95),(0.95,1.0)]:
    cnt = sum(1 for c in confs if lo <= c < hi)
    print(f"  [{lo:.2f},{hi:.2f}): {cnt}")

tiled_only = [b for b in all_boxes if b["source_engines"] == ["rtdetr-v2-tiled"]]
print(f"\n副引擎纯新增框: {len(tiled_only)}")
for b in sorted(tiled_only, key=lambda x: x["confidence"]):
    w = b["bbox"][2]-b["bbox"][0]
    h = b["bbox"][3]-b["bbox"][1]
    ratio = max(w,h)/min(w,h) if min(w,h)>0 else 0
    print(f"  {b['page']} {b['region_id']}: conf={b['confidence']:.4f}, {w:.0f}x{h:.0f}, ratio={ratio:.1f}, {b['bubble_type']}")

main_low = [b for b in all_boxes if "rtdetr-v2" in b["source_engines"] and b["confidence"] < 0.85]
print(f"\n主引擎框 conf < 0.85: {len(main_low)}")
for b in sorted(main_low, key=lambda x: x["confidence"]):
    print(f"  {b['page']} {b['region_id']}: conf={b['confidence']:.4f}, {b['bubble_type']}")
