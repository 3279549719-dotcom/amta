import json
data = json.loads(open("workspace/exp-q1-tiling-garbled/q1_target_audit/q1_target_boxes.json", encoding="utf-8").read())
print(f"总框数: {len(data)}")
for b in data:
    t = b.get("translation", "")
    ocr = b.get("ocr_text", "")[:20]
    print(f"  p{b['page']} {b['region_id']}: ocr='{ocr}' trans='{t[:30]}' (len={len(t)})")
