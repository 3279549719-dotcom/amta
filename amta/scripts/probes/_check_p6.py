import json, os

ws = r"E:\manga translator agent\amta\workspace\touhou-remove-geo-rules\artifacts"

# p6 canon
canon_path = os.path.join(ws, "canon", "page_6.json")
d = json.load(open(canon_path, encoding="utf-8"))
print("=== p6 OCR canon ===")
print(f"rule_filter: raw={d['rule_filter']['raw']}, kept={d['rule_filter']['kept']}, removed={d['rule_filter']['removed']}")
print(f"removed_by_reason: {d['rule_filter']['removed_by_reason']}")
print(f"\n保留的框（{len(d['items'])}个）:")
for item in d['items']:
    rid = item['region_id']
    text = item.get('baberu_text', '')
    bbox = item.get('bbox', [0,0,0,0])
    w = int(bbox[2] - bbox[0])
    h = int(bbox[3] - bbox[1])
    aspect = max(w/h, h/w) if w and h else 0
    print(f"  {rid}: {w}x{h} aspect={aspect:.1f} text='{text[:50]}'")

# p6 translation
trans_path = os.path.join(ws, "translation", "page_6.json")
if os.path.exists(trans_path):
    t = json.load(open(trans_path, encoding="utf-8"))
    print(f"\n=== p6 翻译结果 ===")
    translations = t.get('translations', {})
    for rid, trans in translations.items():
        # 找对应的OCR原文
        ocr_text = ""
        for item in d['items']:
            if item['region_id'] == rid:
                ocr_text = item.get('baberu_text', '')
                break
        print(f"  {rid}:")
        print(f"    原文: {ocr_text[:50]}")
        print(f"    译文: {trans[:50]}")
else:
    print(f"\n翻译文件不存在: {trans_path}")

# 对比旧规则下p6的情况
old_canon_path = r"E:\manga translator agent\amta\workspace\touhou-tiling-e2e\artifacts\canon\page_6.json"
if os.path.exists(old_canon_path):
    old = json.load(open(old_canon_path, encoding="utf-8"))
    print(f"\n=== 对比：旧规则下p6 ===")
    print(f"旧规则: raw={old['rule_filter']['raw']}, kept={old['rule_filter']['kept']}, removed={old['rule_filter']['removed']}")
    print(f"旧规则 removed_by_reason: {old['rule_filter']['removed_by_reason']}")
    print(f"旧规则保留的框数: {len(old['items'])}")
    print(f"新规则保留的框数: {len(d['items'])}")
    print(f"多保留了: {len(d['items']) - len(old['items'])}个框（应该是t08黑竖条）")
