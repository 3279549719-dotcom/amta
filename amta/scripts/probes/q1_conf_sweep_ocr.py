"""Q1 实验第二步：对 B 组（conf=0.3）检测结果跑 OCR，验证增量框的假框过滤效果。

核心问题：主链降 conf 带来的 57 个增量框，OCR confidence（first_token_conf < 0.4）能拦住多少？

输出：
  - workspace/exp-q1-conf-sweep/ocr/page_*_canon.json
  - workspace/exp-q1-conf-sweep/ocr/q1_ocr_result.json
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# 清除代理，避免 OCR 模型下载走代理
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from amta.ocr_station import ocr_page  # noqa: E402

# ---- 路径 ----
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
CONF_SWEEP_DIR = PROJECT_ROOT / "workspace" / "exp-q1-conf-sweep"
B_DET_JSON = CONF_SWEEP_DIR / "artifacts" / "conf03_detection.json"
A_DET_DIR = PROJECT_ROOT / "workspace" / "exp-q1-tiling-garbled" / "artifacts" / "detection"
OCR_OUT_DIR = CONF_SWEEP_DIR / "ocr"
OCR_OUT_DIR.mkdir(parents=True, exist_ok=True)

WORK_ID = "exp-q1-conf-sweep-ocr"

# 匹配容差
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
    """加载 B 组（conf=0.3）检测结果。"""
    data = json.loads(B_DET_JSON.read_text(encoding="utf-8"))
    result = {}
    for key, val in data.items():
        page_idx = int(key.replace("page_", ""))
        result[page_idx] = val["blocks"]
    return result


def load_a_main_boxes(page_idx: int) -> list[dict]:
    """加载 A 组主链框（排除瓦片新增框）。"""
    path = A_DET_DIR / f"page_{page_idx}_detection.json"
    if not path.exists():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [b for b in doc["blocks"] if "rtdetr-v2-tiled" not in b.get("source_engines", [])]


def is_incremental(b_bbox: list[float], a_boxes: list[dict]) -> bool:
    """判断 B 组的框是否是增量框（A 组主链中不存在）。"""
    for a in a_boxes:
        if iou(b_bbox, a["bbox"]) >= IOU_THRESH:
            return False
    return True


def main():
    print("=" * 70)
    print("Q1 实验第二步：B 组（conf=0.3）OCR 验证 — 增量框假框过滤")
    print("=" * 70)

    b_results = load_b_det()
    target_pages = sorted(b_results.keys())
    print(f"\n目标页: {len(target_pages)} 页")

    # ---- 跑 OCR ----
    print(f"\n{'─' * 70}")
    print("Step 1: 对 B 组全部框跑 OCR（hayai, conf过滤开启, rule_filter关闭）")
    print(f"{'─' * 70}")

    all_canon = {}
    all_trace = {}
    t0 = time.time()

    for page_idx in target_pages:
        raw_path = RAW_DIR / f"{page_idx}.jpg"
        if not raw_path.exists():
            print(f"  p{page_idx}: 原图不存在，跳过")
            continue

        blocks = b_results[page_idx]
        # 构造标准 detection doc
        det_doc = {
            "work_id": WORK_ID,
            "page": f"page_{page_idx}",
            "blocks": blocks,
            "n_boxes": len(blocks),
        }

        page_out = OCR_OUT_DIR / f"page_{page_idx}"
        page_out.mkdir(parents=True, exist_ok=True)

        print(f"  p{page_idx}: {len(blocks)} 框, 跑 OCR...", end=" ", flush=True)
        try:
            canon = ocr_page(
                WORK_ID, det_doc, raw_path, OCR_OUT_DIR,
                page_idx=page_idx, engine="hayai",
                vlm_enabled=False, rule_filter_enabled=False,
                crop_dir=page_out / "crops",
            )
            n_kept = canon["n_regions"]
            n_conf_removed = canon.get("n_conf_removed", 0)
            all_canon[page_idx] = canon

            # 读取 trace 获取被过滤框的详情
            trace_path = OCR_OUT_DIR / f"page_{page_idx}_02_ocr_trace.json"
            if trace_path.exists():
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
                all_trace[page_idx] = trace

            print(f"保留 {n_kept}, 过滤 {n_conf_removed}")
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    elapsed = time.time() - t0
    print(f"\nOCR 完成，耗时 {elapsed:.1f}s ({elapsed/60:.1f}min)")

    # ---- 增量框分析 ----
    print(f"\n{'─' * 70}")
    print("Step 2: 增量框（B有A无）的 OCR 过滤分析")
    print(f"{'─' * 70}")

    incremental_boxes = []  # 所有增量框
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

    # 对每个增量框，查 OCR 结果：是否被保留，OCR 文本，first_token_conf
    incr_results = []
    for inc in incremental_boxes:
        page_idx = inc["page"]
        rid = inc["region_id"]
        canon = all_canon.get(page_idx)
        trace = all_trace.get(page_idx, {})

        # 查是否被保留
        kept_region = None
        if canon:
            for r in canon.get("regions", []):
                if r.get("region_id") == rid:
                    kept_region = r
                    break

        # 查是否被 conf 过滤
        conf_removed = None
        for cr in trace.get("conf_removed_details", []):
            if cr.get("region_id") == rid:
                conf_removed = cr
                break

        if kept_region:
            status = "KEPT"
            ocr_text = kept_region.get("text", "")
            first_conf = kept_region.get("first_token_conf", 0)
        elif conf_removed:
            status = "CONF_FILTERED"
            ocr_text = conf_removed.get("text", "")
            first_conf = conf_removed.get("first_token_conf", 0)
        else:
            status = "UNKNOWN"
            ocr_text = ""
            first_conf = 0

        incr_results.append({
            **inc,
            "status": status,
            "ocr_text": ocr_text,
            "first_token_conf": first_conf,
        })

    # 统计
    n_kept = sum(1 for r in incr_results if r["status"] == "KEPT")
    n_filtered = sum(1 for r in incr_results if r["status"] == "CONF_FILTERED")
    n_unknown = sum(1 for r in incr_results if r["status"] == "UNKNOWN")

    print(f"\n【增量框 OCR 结果统计】")
    print(f"  总数: {len(incr_results)}")
    print(f"  保留 (KEPT): {n_kept} ({n_kept/len(incr_results)*100:.1f}%)")
    print(f"  被conf过滤 (CONF_FILTERED): {n_filtered} ({n_filtered/len(incr_results)*100:.1f}%)")
    print(f"  未知: {n_unknown}")

    # 保留的增量框详情（这些是"漏网的假框"或"真小字"）
    kept_incr = [r for r in incr_results if r["status"] == "KEPT"]
    if kept_incr:
        print(f"\n【保留的增量框详情（{len(kept_incr)} 个）— 需要人工判断真假】")
        print(f"{'页':<5} {'ID':<6} {'det_conf':<10} {'first_conf':<12} {'OCR文本':<30}")
        print("-" * 70)
        for r in sorted(kept_incr, key=lambda x: x["first_token_conf"]):
            print(f"p{r['page']:<4} {r['region_id']:<6} {r['det_conf']:<10.4f} "
                  f"{r['first_token_conf']:<12.4f} {r['ocr_text'][:28]:<30}")

    # 被过滤的增量框详情
    filtered_incr = [r for r in incr_results if r["status"] == "CONF_FILTERED"]
    if filtered_incr:
        print(f"\n【被conf过滤的增量框详情（{len(filtered_incr)} 个）— 成功拦截的假框】")
        print(f"{'页':<5} {'ID':<6} {'det_conf':<10} {'first_conf':<12} {'OCR文本':<30}")
        print("-" * 70)
        for r in sorted(filtered_incr, key=lambda x: x["first_token_conf"]):
            print(f"p{r['page']:<4} {r['region_id']:<6} {r['det_conf']:<10.4f} "
                  f"{r['first_token_conf']:<12.4f} {r['ocr_text'][:28]:<30}")

    # ---- 全量框 OCR 统计（对比基线）----
    print(f"\n{'─' * 70}")
    print("Step 3: B 组全量框 OCR 统计（对比参考）")
    print(f"{'─' * 70}")

    total_b_boxes = sum(len(b_results.get(p, [])) for p in target_pages)
    total_kept = sum(c.get("n_regions", 0) for c in all_canon.values())
    total_conf_removed = sum(c.get("n_conf_removed", 0) for c in all_canon.values())

    print(f"\n  B 组总框数: {total_b_boxes}")
    print(f"  OCR 后保留: {total_kept}")
    print(f"  conf过滤: {total_conf_removed}")
    print(f"  全量过滤率: {total_conf_removed/total_b_boxes*100:.1f}%" if total_b_boxes else "N/A")
    print(f"  增量框过滤率: {n_filtered/len(incr_results)*100:.1f}%" if incr_results else "N/A")

    # ---- 保存结果 ----
    result = {
        "experiment": "q1_conf_sweep_ocr",
        "incremental_total": len(incr_results),
        "incremental_kept": n_kept,
        "incremental_conf_filtered": n_filtered,
        "incremental_filter_rate": n_filtered / len(incr_results) if incr_results else 0,
        "total_b_boxes": total_b_boxes,
        "total_ocr_kept": total_kept,
        "total_conf_removed": total_conf_removed,
        "incremental_details": incr_results,
    }
    out_path = OCR_OUT_DIR / "q1_ocr_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已保存: {out_path}")

    # ---- 结论 ----
    print(f"\n{'=' * 70}")
    if n_filtered / len(incr_results) >= 0.7:
        print(f"结论倾向：增量框 {n_filtered}/{len(incr_results)} 被OCR过滤，过滤率≥70%")
        print("→ 主链降conf带来的假框大部分能被OCR拦住，降conf方案可行")
    elif n_filtered / len(incr_results) >= 0.5:
        print(f"结论倾向：增量框 {n_filtered}/{len(incr_results)} 被OCR过滤，过滤率约50%")
        print("→ 部分假框能被拦住，但仍有较多漏网，需评估保留增量框的代价")
    else:
        print(f"结论倾向：增量框仅 {n_filtered}/{len(incr_results)} 被OCR过滤")
        print("→ OCR拦不住大部分假框，主链降conf代价太大，不建议单独使用")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
