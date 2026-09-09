"""Q1 实验第三步：从已有 OCR 结果中提取增量框的 first_token_conf 分布。

背景：OCR confidence 过滤只对 tiled-only 框生效，主链框不过滤。
但 OCR 结果里每个框都有 first_token_conf，我们可以手动分析增量框的 conf 分布，
判断如果把过滤扩展到主链低 conf 框，能不能拦住假框。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ---- 路径 ----
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
CONF_SWEEP_DIR = PROJECT_ROOT / "workspace" / "exp-q1-conf-sweep"
B_DET_JSON = CONF_SWEEP_DIR / "artifacts" / "conf03_detection.json"
A_DET_DIR = PROJECT_ROOT / "workspace" / "exp-q1-tiling-garbled" / "artifacts" / "detection"
OCR_DIR = CONF_SWEEP_DIR / "ocr"

IOU_THRESH = 0.3


def iou(a: list[float], b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = a[:4]
    bx0, by0, bx1, by1 = b[:4]
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua > 0 else 0.0


def load_b_det() -> dict[int, list[dict]]:
    data = json.loads(B_DET_JSON.read_text(encoding="utf-8"))
    result = {}
    for key, val in data.items():
        page_idx = int(key.replace("page_", ""))
        result[page_idx] = val["blocks"]
    return result


def load_a_main_boxes(page_idx: int) -> list[dict]:
    path = A_DET_DIR / f"page_{page_idx}_detection.json"
    if not path.exists():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [b for b in doc["blocks"] if "rtdetr-v2-tiled" not in b.get("source_engines", [])]


def is_incremental(b_bbox: list[float], a_boxes: list[dict]) -> bool:
    for a in a_boxes:
        if iou(b_bbox, a["bbox"]) >= IOU_THRESH:
            return False
    return True


def load_canon(page_idx: int) -> dict | None:
    """加载 OCR canon 结果。"""
    canon_path = OCR_DIR / "canon" / f"page_{page_idx}.json"
    if not canon_path.exists():
        return None
    return json.loads(canon_path.read_text(encoding="utf-8"))


def main():
    print("=" * 70)
    print("Q1 第三步：增量框的 OCR confidence 分布分析（手动扩展过滤）")
    print("=" * 70)

    b_results = load_b_det()
    target_pages = sorted(b_results.keys())

    # 找出所有增量框
    incremental_boxes = []
    for page_idx in target_pages:
        b_blocks = b_results.get(page_idx, [])
        a_blocks = load_a_main_boxes(page_idx)
        for b in b_blocks:
            if is_incremental(b["bbox"], a_blocks):
                incremental_boxes.append({
                    "page": page_idx,
                    "region_id": b["region_id"],
                    "bbox": b["bbox"],
                    "det_conf": b["confidence"],
                })

    print(f"\n增量框总数: {len(incremental_boxes)}")

    # 从 canon 中提取每个增量框的 OCR 结果
    print(f"\n{'─' * 70}")
    print("增量框 OCR 详情（按 first_token_conf 升序）")
    print(f"{'─' * 70}")
    print(f"{'页':<5} {'ID':<6} {'det_conf':<10} {'first_conf':<12} {'avg_conf':<10} {'OCR文本':<35}")
    print("-" * 85)

    incr_with_ocr = []
    for inc in incremental_boxes:
        page_idx = inc["page"]
        rid = inc["region_id"]
        canon = load_canon(page_idx)
        if canon is None:
            print(f"p{page_idx:<4} {rid:<6} canon not found")
            continue

        ocr_text = ""
        first_conf = 1.0
        avg_conf = 1.0
        for r in canon.get("items", []):
            if r.get("region_id") == rid:
                ocr_text = r.get("text", "")
                first_conf = r.get("first_token_conf", 1.0)
                avg_conf = r.get("avg_conf", 1.0)
                break

        incr_with_ocr.append({
            **inc,
            "ocr_text": ocr_text,
            "first_token_conf": first_conf,
            "avg_conf": avg_conf,
        })

    for r in sorted(incr_with_ocr, key=lambda x: x["first_token_conf"]):
        print(f"p{r['page']:<4} {r['region_id']:<6} {r['det_conf']:<10.4f} "
              f"{r['first_token_conf']:<12.4f} {r['avg_conf']:<10.4f} {r['ocr_text'][:33]:<35}")

    # ---- 统计分析 ----
    print(f"\n{'─' * 70}")
    print("统计分析")
    print(f"{'─' * 70}")

    first_confs = [r["first_token_conf"] for r in incr_with_ocr]
    det_confs = [r["det_conf"] for r in incr_with_ocr]

    print(f"\n【first_token_conf 分布】")
    print(f"  最小: {min(first_confs):.4f}")
    print(f"  最大: {max(first_confs):.4f}")
    print(f"  平均: {sum(first_confs)/len(first_confs):.4f}")
    print(f"  中位数: {sorted(first_confs)[len(first_confs)//2]:.4f}")

    thresholds = [0.3, 0.4, 0.5, 0.6, 0.7]
    print(f"\n  不同阈值下的过滤数量：")
    for th in thresholds:
        n_below = sum(1 for c in first_confs if c < th)
        print(f"    first_conf < {th}: {n_below} 个 ({n_below/len(first_confs)*100:.1f}%)")

    # ---- 模拟扩展过滤 ----
    print(f"\n{'─' * 70}")
    print("模拟：如果对主链框也应用 first_token_conf < 0.4 过滤")
    print(f"{'─' * 70}")

    OCR_THRESH = 0.4
    would_filter = [r for r in incr_with_ocr if r["first_token_conf"] < OCR_THRESH]
    would_keep = [r for r in incr_with_ocr if r["first_token_conf"] >= OCR_THRESH]

    print(f"\n  会被过滤: {len(would_filter)} 个")
    if would_filter:
        print(f"  被过滤的框：")
        for r in sorted(would_filter, key=lambda x: x["first_token_conf"]):
            print(f"    p{r['page']} {r['region_id']}: first_conf={r['first_token_conf']:.4f}, "
                  f"OCR='{r['ocr_text'][:30]}'")

    print(f"\n  会被保留: {len(would_keep)} 个")
    if would_keep:
        print(f"  保留的框（需要人工判断真假）：")
        for r in sorted(would_keep, key=lambda x: x["first_token_conf"]):
            print(f"    p{r['page']} {r['region_id']}: first_conf={r['first_token_conf']:.4f}, "
                  f"det_conf={r['det_conf']:.4f}, OCR='{r['ocr_text'][:30]}'")

    # ---- det_conf 和 first_conf 的相关性 ----
    print(f"\n{'─' * 70}")
    print("det_conf vs first_token_conf 对比")
    print(f"{'─' * 70}")
    print(f"  det_conf 平均: {sum(det_confs)/len(det_confs):.4f}")
    print(f"  first_conf 平均: {sum(first_confs)/len(first_confs):.4f}")

    # 有多少增量框 det_conf < 0.5 但 first_conf >= 0.4（可能是真小字）
    low_det_high_ocr = [r for r in incr_with_ocr if r["det_conf"] < 0.5 and r["first_token_conf"] >= 0.4]
    print(f"\n  det_conf<0.5 且 first_conf>=0.4 的框（可能是真小字）: {len(low_det_high_ocr)} 个")
    for r in low_det_high_ocr:
        print(f"    p{r['page']} {r['region_id']}: det={r['det_conf']:.4f}, "
              f"first={r['first_token_conf']:.4f}, OCR='{r['ocr_text'][:30]}'")

    # ---- 保存结果 ----
    result = {
        "incremental_total": len(incr_with_ocr),
        "first_conf_stats": {
            "min": min(first_confs),
            "max": max(first_confs),
            "mean": sum(first_confs) / len(first_confs),
            "median": sorted(first_confs)[len(first_confs) // 2],
        },
        "filter_at_0.4": {
            "would_filter": len(would_filter),
            "would_keep": len(would_keep),
            "filter_rate": len(would_filter) / len(incr_with_ocr),
        },
        "details": incr_with_ocr,
    }
    out_path = OCR_DIR / "q1_incremental_ocr_analysis.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已保存: {out_path}")


if __name__ == "__main__":
    main()
