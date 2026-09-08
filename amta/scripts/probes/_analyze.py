import json
data = json.loads(open("workspace/exp-q1-tiling-garbled/q1_target_audit/q1_target_boxes.json", encoding="utf-8").read())
print(f"总框数: {len(data)}")
empty_trans = [b for b in data if not b.get("translation")]
print(f"翻译为空: {len(empty_trans)}")
for b in empty_trans:
    print(f"  p{b['page']} {b['region_id']} ocr='{b['ocr_text'][:40]}' reasons={b['reasons']}")
print()
for b in data:
    t = b.get("translation", "")
    if t and len(t) > 40:
        print(f"  长翻译 p{b['page']} {b['region_id']}: '{t[:60]}'")
