import json

c = json.load(open(r"E:\manga translator agent\amta\workspace\exp-q1-conf-sweep\ocr\canon\page_2.json", encoding="utf-8"))
print("=== page_2 canon structure ===")
print("n_regions:", c.get("n_regions"))
print("items type:", type(c.get("items")))
if isinstance(c.get("items"), list):
    print("items count:", len(c["items"]))
    for item in c["items"][:3]:
        print("  item keys:", list(item.keys()))
        print("  ", {k: item[k] for k in ["region_id", "text", "first_token_conf", "avg_conf"] if k in item})
elif isinstance(c.get("items"), dict):
    print("items keys:", list(c["items"].keys())[:5])
    # 可能是 {region_id: {...}} 格式
    for rid in list(c["items"].keys())[:3]:
        v = c["items"][rid]
        print(f"  {rid}: keys={list(v.keys()) if isinstance(v, dict) else type(v)}")
        if isinstance(v, dict):
            print(f"    text='{v.get('text','')}', first={v.get('first_token_conf')}")
