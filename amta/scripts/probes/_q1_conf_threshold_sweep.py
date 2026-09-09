"""从conf=0.3的检测结果中按不同conf阈值过滤，预估conf=0.5/0.6的效果。"""
import json
from pathlib import Path

CONF_SWEEP_DIR = Path(r"E:\manga translator agent\amta\workspace\exp-q1-conf-sweep")
B_DET_JSON = CONF_SWEEP_DIR / "artifacts" / "conf03_detection.json"
A_DET_DIR = Path(r"E:\manga translator agent\amta\workspace\exp-q1-tiling-garbled\artifacts\detection")
OCR_DIR = CONF_SWEEP_DIR / "ocr"

IOU_THRESH = 0.3

def iou(a, b):
    ax0, ay0, ax1, ay1 = a[:4]
    bx0, by0, bx1, by1 = b[:4]
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    ua = (ax1-ax0)*(ay1-ay0) + (bx1-bx0)*(by1-by0) - inter
    return inter/ua if ua > 0 else 0.0

def load_b_det():
    data = json.loads(B_DET_JSON.read_text(encoding="utf-8"))
    result = {}
    for key, val in data.items():
        page_idx = int(key.replace("page_", ""))
        result[page_idx] = val["blocks"]
    return result

def load_a_main_boxes(page_idx):
    path = A_DET_DIR / f"page_{page_idx}_detection.json"
    if not path.exists():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [b for b in doc["blocks"] if "rtdetr-v2-tiled" not in b.get("source_engines", [])]

def load_ocr(page_idx):
    canon_path = OCR_DIR / "canon" / f"page_{page_idx}.json"
    if not canon_path.exists():
        return {}
    doc = json.loads(canon_path.read_text(encoding="utf-8"))
    return {item["region_id"]: item for item in doc.get("items", [])}

def is_incremental(bbox, a_boxes):
    for a in a_boxes:
        if iou(bbox, a["bbox"]) >= IOU_THRESH:
            return False
    return True

b_results = load_b_det()
target_pages = sorted(b_results.keys())

# 加载所有OCR结果
ocr_all = {}
for p in target_pages:
    ocr_all[p] = load_ocr(p)

for conf_thresh in [0.4, 0.5, 0.6]:
    print(f"\n{'='*70}")
    print(f"主链 conf >= {conf_thresh} 的预估结果")
    print(f"{'='*70}")

    total_boxes = 0
    incremental_boxes = []
    for page_idx in target_pages:
        a_boxes = load_a_main_boxes(page_idx)
        b_boxes = [b for b in b_results[page_idx] if b["confidence"] >= conf_thresh]
        total_boxes += len(b_boxes)
        for b in b_boxes:
            if is_incremental(b["bbox"], a_boxes):
                ocr = ocr_all.get(page_idx, {}).get(b["region_id"], {})
                incremental_boxes.append({
                    "page": page_idx,
                    "rid": b["region_id"],
                    "det_conf": b["confidence"],
                    "ocr_text": ocr.get("text", ""),
                    "first_conf": ocr.get("first_token_conf", 1.0),
                })

    print(f"\n  总框数（17页）: {total_boxes}")
    print(f"  增量框数（B有A无）: {len(incremental_boxes)}")

    # 按OCR first_conf分类
    ocr_filtered = [b for b in incremental_boxes if b["first_conf"] < 0.4]
    ocr_kept = [b for b in incremental_boxes if b["first_conf"] >= 0.4]

    print(f"\n  经过OCR过滤(first_conf<0.4)后：")
    print(f"    被过滤: {len(ocr_filtered)} 个")
    print(f"    保留: {len(ocr_kept)} 个")

    if ocr_kept:
        print(f"\n  保留的增量框详情：")
        print(f"  {'页':<5} {'ID':<6} {'det_conf':<10} {'first_conf':<12} {'OCR文本':<30}")
        print("  " + "-"*65)
        for b in sorted(ocr_kept, key=lambda x: x["first_conf"]):
            print(f"  p{b['page']:<4} {b['rid']:<6} {b['det_conf']:<10.4f} "
                  f"{b['first_conf']:<12.4f} {b['ocr_text'][:28]:<30}")

    if ocr_filtered:
        print(f"\n  被过滤的增量框（前5个）：")
        for b in sorted(ocr_filtered, key=lambda x: x["first_conf"])[:5]:
            print(f"    p{b['page']} {b['rid']}: det={b['det_conf']:.4f}, first={b['first_conf']:.4f}, OCR='{b['ocr_text'][:20]}'")

# 对比汇总
print(f"\n{'='*70}")
print("不同conf阈值对比汇总")
print(f"{'='*70}")
print(f"{'阈值':<8} {'总框数':<10} {'增量框':<10} {'OCR过滤后保留':<15} {'真小字(高OCR)':<15}")
print("-"*60)

for conf_thresh in [0.7, 0.6, 0.5, 0.4, 0.3]:
    total = 0
    incr = []
    for page_idx in target_pages:
        a_boxes = load_a_main_boxes(page_idx)
        if conf_thresh == 0.7:
            # 0.7就是A组主链
            total += len(a_boxes)
            continue
        b_boxes = [b for b in b_results[page_idx] if b["confidence"] >= conf_thresh]
        total += len(b_boxes)
        for b in b_boxes:
            if is_incremental(b["bbox"], a_boxes):
                ocr = ocr_all.get(page_idx, {}).get(b["region_id"], {})
                incr.append({
                    "first_conf": ocr.get("first_token_conf", 1.0),
                    "ocr_text": ocr.get("text", ""),
                })

    if conf_thresh == 0.7:
        print(f"{conf_thresh:<8} {total:<10} {'0':<10} {'0':<15} {'0':<15} (基线)")
    else:
        kept = [b for b in incr if b["first_conf"] >= 0.4]
        real_text = [b for b in kept if len(b["ocr_text"]) >= 2 and b["first_conf"] >= 0.9]
        print(f"{conf_thresh:<8} {total:<10} {len(incr):<10} {len(kept):<15} {len(real_text):<15}")
