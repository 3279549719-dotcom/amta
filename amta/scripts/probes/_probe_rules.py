"""探查所有workspace的canon，对比9个滤除框的存在情况。"""
import json, glob, os

# 9个滤除框：(page, region_id, rule)
TARGETS = [
    ("page_2", "t04", "pure_punct?"),
    ("page_6", "t08", "extreme_aspect"),
    ("page_13", "r01", "extreme_aspect"),
    ("page_16", "r03", "edge_box"),
    ("page_20", "r00", "edge_box"),
    ("page_22", "r08", "edge_box"),
    ("page_31", "t08", "extreme_aspect"),
    ("page_33", "r01", "extreme_aspect"),
    ("page_41", "r00", "extreme_aspect"),
]

# 找所有有canon的workspace
workspaces = set()
for f in glob.glob(r"E:\manga translator agent\amta\workspace\*\artifacts\canon\*.json"):
    ws = f.split("workspace")[1].split("artifacts")[0].strip("\\")
    workspaces.add(ws)

print(f"=== 发现 {len(workspaces)} 个有canon的workspace ===")
for ws in sorted(workspaces):
    canon_dir = rf"E:\manga translator agent\amta\workspace\{ws}\artifacts\canon"
    n_files = len(glob.glob(os.path.join(canon_dir, "page_*.json")))
    # 看page_13的rule_filter状态
    p13 = os.path.join(canon_dir, "page_13.json")
    if os.path.exists(p13):
        d = json.load(open(p13, encoding="utf-8"))
        rf = d.get("rule_filter", {})
        rfe = d.get("rule_filter_enabled", "N/A")
        ids = [item["region_id"] for item in d.get("items", [])]
        has_r01 = "r01" in ids
        print(f"  {ws}: {n_files}页, p13 rule_enabled={rfe}, raw={rf.get('raw')}, kept={rf.get('kept')}, removed={rf.get('removed')}, r01存在={has_r01}")
    else:
        print(f"  {ws}: {n_files}页, 无p13")

print("\n=== 9个滤除框在各workspace中的存在情况 ===")
print(f"{'workspace':<30} {'p2t04':<6} {'p6t08':<6} {'p13r01':<7} {'p16r03':<7} {'p20r00':<7} {'p22r08':<7} {'p31t08':<7} {'p33r01':<7} {'p41r00':<7}")

for ws in sorted(workspaces):
    canon_dir = rf"E:\manga translator agent\amta\workspace\{ws}\artifacts\canon"
    row = [ws[:28]]
    for page, rid, rule in TARGETS:
        f = os.path.join(canon_dir, f"{page}.json")
        if os.path.exists(f):
            d = json.load(open(f, encoding="utf-8"))
            ids = [item["region_id"] for item in d.get("items", [])]
            row.append("Y" if rid in ids else "N")
        else:
            row.append("-")
    print(f"{row[0]:<30} {row[1]:<6} {row[2]:<6} {row[3]:<7} {row[4]:<7} {row[5]:<7} {row[6]:<7} {row[7]:<7} {row[8]:<7} {row[9]:<7}")

# 详细看tiling-e2e的9个框的OCR文本（detection里有但canon里没有的）
print("\n=== tiling-e2e: 9个滤除框的detection信息 + OCR文本 ===")
det_dir = r"E:\manga translator agent\amta\workspace\touhou-tiling-e2e\artifacts\detection"
canon_dir = r"E:\manga translator agent\amta\workspace\touhou-tiling-e2e\artifacts\canon"

for page, rid, rule in TARGETS:
    det_f = os.path.join(det_dir, f"{page}.json")
    canon_f = os.path.join(canon_dir, f"{page}.json")
    if not os.path.exists(det_f):
        print(f"  {page} {rid}: detection文件不存在")
        continue
    det = json.load(open(det_f, encoding="utf-8"))
    det_blocks = {b["region_id"]: b for b in det.get("blocks", [])}
    if rid not in det_blocks:
        print(f"  {page} {rid}: detection中不存在")
        continue
    b = det_blocks[rid]
    bbox = b["bbox"]
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    aspect = max(w/h, h/w)
    conf = b.get("confidence", 0)
    btype = b.get("bubble_type", "?")
    
    # 看canon里的rule_filter统计
    canon = json.load(open(canon_f, encoding="utf-8")) if os.path.exists(canon_f) else {}
    rf = canon.get("rule_filter", {})
    
    # 找OCR文本：看ocr_trace文件
    ocr_trace = rf"E:\manga translator agent\amta\workspace\touhou-tiling-e2e\artifacts\{page}_02_ocr_trace.json"
    ocr_text = "N/A"
    if os.path.exists(ocr_trace):
        trace = json.load(open(ocr_trace, encoding="utf-8"))
        # trace结构需要探查
        if isinstance(trace, dict):
            for k, v in trace.items():
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict) and item.get("region_id") == rid:
                            ocr_text = item.get("text", item.get("baberu_text", "?"))
                            break
                elif isinstance(v, dict) and rid in v:
                    ocr_text = v[rid].get("text", "?")
    
    print(f"  {page} {rid}: {w:.0f}x{h:.0f}, aspect={aspect:.1f}, conf={conf:.3f}, type={btype}, rule={rule}, OCR='{ocr_text}'")
    print(f"    canon rule_filter: raw={rf.get('raw')}, kept={rf.get('kept')}, removed={rf.get('removed')}, reasons={rf.get('removed_by_reason')}")
