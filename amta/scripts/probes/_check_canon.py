import json, glob, os

canon_dir = r"E:\manga translator agent\amta\workspace\touhou-remove-geo-rules\artifacts\canon"
files = sorted(glob.glob(os.path.join(canon_dir, "page_*.json")))
print(f"已完成OCR的页数: {len(files)}")

total_kept = 0
total_raw = 0
total_removed = 0
for f in files:
    d = json.load(open(f, encoding="utf-8"))
    rf = d.get("rule_filter", {})
    total_kept += rf.get("kept", 0)
    total_raw += rf.get("raw", 0)
    total_removed += rf.get("removed", 0)
    page = d.get("page", "?")
    if rf.get("removed", 0) > 0:
        reasons = rf.get("removed_by_reason", {})
        print(f"  {page}: raw={rf.get('raw')}, kept={rf.get('kept')}, removed={rf.get('removed')}, reasons={reasons}")

print(f"\n汇总（已完成{len(files)}页）: raw={total_raw}, kept={total_kept}, removed={total_removed}")
print(f"被过滤的框数: {total_removed}（旧规则全40页是9个）")

# 检查p6的canon，看黑竖条是否流下来了
p6_path = os.path.join(canon_dir, "page_6.json")
if os.path.exists(p6_path):
    d = json.load(open(p6_path, encoding="utf-8"))
    print(f"\n=== p6 详情 ===")
    print(f"raw={d['rule_filter']['raw']}, kept={d['rule_filter']['kept']}, removed={d['rule_filter']['removed']}")
    for item in d.get("items", []):
        rid = item.get("region_id")
        text = item.get("baberu_text", "")[:30]
        bbox = item.get("bbox")
        w = int(bbox[2] - bbox[0]) if bbox else 0
        h = int(bbox[3] - bbox[1]) if bbox else 0
        aspect = max(w/h, h/w) if w and h else 0
        print(f"  {rid}: {w}x{h} aspect={aspect:.1f} text='{text}'")
