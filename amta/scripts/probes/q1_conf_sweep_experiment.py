"""Q1 实验：主链 conf=0.3 vs 瓦片副引擎 — detect 阶段对比。

核心问题：瓦片捡回来的小字框，主链直接降 conf 到 0.3 能不能直接捞到？

三组：
  A: 主链 conf=0.7（基线，已有数据）
  B: 主链 conf=0.3，无瓦片（实验）
  C: 主链 0.7 + 瓦片（已有数据，20个新增框）

指标：
  1. C 的瓦片新增框在 B 中的命中率
  2. 命中框在整图下的 conf 分布
  3. B vs A 的框数增量（假框）
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from amta.detect_station import RTDetrDetector  # noqa: E402

# ---- 路径 ----
RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
AUDIT_JSON = PROJECT_ROOT / "workspace" / "exp-q1-tiling-garbled" / "artifacts" / "q1_audit_summary.json"
DET_DIR_A = PROJECT_ROOT / "workspace" / "exp-q1-tiling-garbled" / "artifacts" / "detection"
OUT_DIR = PROJECT_ROOT / "workspace" / "exp-q1-conf-sweep" / "artifacts"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 匹配容差：IoU >= 0.3 视为同一框（瓦片框与主链框位置可能有偏差）
IOU_THRESH = 0.3


def iou(a: list[float], b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = a[:4]
    bx0, by0, bx1, by1 = b[:4]
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua > 0 else 0.0


def load_tiled_targets() -> list[dict]:
    """从 audit summary 加载瓦片新增框目标。"""
    audit = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    return audit["tiled_new_boxes"]


def load_baseline_a(page_idx: int) -> dict | None:
    """加载 A 组（主链 conf=0.7 + 瓦片）的检测结果，提取主链框。"""
    path = DET_DIR_A / f"page_{page_idx}_detection.json"
    if not path.exists():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    main_blocks = [b for b in doc["blocks"] if "rtdetr-v2-tiled" not in b.get("source_engines", [])]
    return {"n_main": len(main_blocks), "main_blocks": main_blocks, "n_total": doc["n_boxes"]}


def detect_conf_03(page_idx: int) -> list[dict]:
    """B 组：主链 conf=0.3，无瓦片。"""
    raw_path = RAW_DIR / f"{page_idx}.jpg"
    if not raw_path.exists():
        print(f"  [skip] p{page_idx} 原图不存在")
        return []
    det = RTDetrDetector(conf_threshold=0.3)
    blocks = det.detect(str(raw_path))
    return blocks


def match_target(target_bbox: list[float], blocks: list[dict]) -> dict | None:
    """在 blocks 中找与 target_bbox IoU 最大的匹配。"""
    best = None
    best_iou = 0.0
    for b in blocks:
        v = iou(target_bbox, b["bbox"])
        if v > best_iou:
            best_iou = v
            best = b
    if best_iou >= IOU_THRESH:
        return {"block": best, "iou": best_iou}
    return None


def main():
    print("=" * 70)
    print("Q1 实验：主链 conf=0.3 vs 瓦片副引擎 — detect 阶段")
    print("=" * 70)

    targets = load_tiled_targets()
    target_pages = sorted(set(t["page"] for t in targets))
    print(f"\n瓦片新增框目标: {len(targets)} 个，分布在 {len(target_pages)} 页")
    print(f"目标页: {target_pages}")

    # ---- 跑 B 组（主链 conf=0.3）----
    print(f"\n{'─' * 70}")
    print("Step 1: 跑 B 组（主链 conf=0.3，无瓦片）")
    print(f"{'─' * 70}")

    b_results: dict[int, list[dict]] = {}
    t0 = time.time()
    for page_idx in target_pages:
        print(f"  [detect] p{page_idx} ...", flush=True)
        blocks = detect_conf_03(page_idx)
        b_results[page_idx] = blocks
        print(f"           → {len(blocks)} boxes")
    elapsed = time.time() - t0
    print(f"\nB 组完成，耗时 {elapsed:.1f}s")

    # 保存 B 组结果
    b_summary = {}
    for page_idx, blocks in b_results.items():
        b_summary[f"page_{page_idx}"] = {
            "n_boxes": len(blocks),
            "blocks": blocks,
        }
    (OUT_DIR / "conf03_detection.json").write_text(
        json.dumps(b_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---- 匹配分析 ----
    print(f"\n{'─' * 70}")
    print("Step 2: 匹配瓦片新增框 → B 组命中率")
    print(f"{'─' * 70}")

    hit_results = []
    for t in targets:
        page_idx = t["page"]
        target_bbox = t["bbox"]
        tiled_conf = t["confidence"]
        rid = t["region_id"]

        b_blocks = b_results.get(page_idx, [])
        match = match_target(target_bbox, b_blocks)

        if match:
            hit_results.append({
                "page": page_idx,
                "region_id": rid,
                "tiled_conf": tiled_conf,
                "hit": True,
                "main_conf": match["block"]["confidence"],
                "iou": match["iou"],
                "main_bbox": match["block"]["bbox"],
                "target_bbox": target_bbox,
            })
            status = f"HIT  main_conf={match['block']['confidence']:.4f}  iou={match['iou']:.3f}"
        else:
            # 找最接近的（即使 IoU 不够）
            best_iou = 0.0
            best_conf = 0.0
            for b in b_blocks:
                v = iou(target_bbox, b["bbox"])
                if v > best_iou:
                    best_iou = v
                    best_conf = b["confidence"]
            hit_results.append({
                "page": page_idx,
                "region_id": rid,
                "tiled_conf": tiled_conf,
                "hit": False,
                "main_conf": None,
                "iou": best_iou,
                "best_iou_conf": best_conf,
                "target_bbox": target_bbox,
            })
            status = f"MISS best_iou={best_iou:.3f} (best_conf={best_conf:.4f})"

        print(f"  p{page_idx:2d} {rid}: tiled_conf={tiled_conf:.4f}  →  {status}")

    # ---- 统计 ----
    print(f"\n{'─' * 70}")
    print("Step 3: 统计汇总")
    print(f"{'─' * 70}")

    n_total = len(hit_results)
    n_hit = sum(1 for h in hit_results if h["hit"])
    n_miss = n_total - n_hit

    print(f"\n【瓦片新增框命中率】")
    print(f"  总数: {n_total}")
    print(f"  命中: {n_hit} ({n_hit/n_total*100:.1f}%)")
    print(f"  未命中: {n_miss} ({n_miss/n_total*100:.1f}%)")

    hit_confs = [h["main_conf"] for h in hit_results if h["hit"]]
    if hit_confs:
        print(f"\n【命中框在整图下的 conf 分布】")
        print(f"  最小: {min(hit_confs):.4f}")
        print(f"  最大: {max(hit_confs):.4f}")
        print(f"  平均: {sum(hit_confs)/len(hit_confs):.4f}")
        print(f"  <0.7: {sum(1 for c in hit_confs if c < 0.7)} 个")
        print(f"  0.7~0.8: {sum(1 for c in hit_confs if 0.7 <= c < 0.8)} 个")
        print(f"  >=0.8: {sum(1 for c in hit_confs if c >= 0.8)} 个")

    # ---- 框数增量对比 ----
    print(f"\n【框数增量对比（B: conf=0.3 vs A: conf=0.7 主链部分）】")
    total_a_main = 0
    total_b = 0
    page_deltas = []
    for page_idx in target_pages:
        a_data = load_baseline_a(page_idx)
        b_blocks = b_results.get(page_idx, [])
        if a_data is None:
            continue
        n_a = a_data["n_main"]
        n_b = len(b_blocks)
        delta = n_b - n_a
        total_a_main += n_a
        total_b += n_b
        page_deltas.append({"page": page_idx, "n_a_main": n_a, "n_b": n_b, "delta": delta})
        print(f"  p{page_idx:2d}: A主链={n_a:2d}  B={n_b:2d}  Δ={delta:+d}")

    print(f"\n  合计: A主链={total_a_main}  B={total_b}  Δ={total_b - total_a_main:+d}")
    print(f"  平均每页增量: {(total_b - total_a_main)/len(target_pages):.1f} 框")

    # ---- 未命中框详情 ----
    misses = [h for h in hit_results if not h["hit"]]
    if misses:
        print(f"\n【未命中框详情（{len(misses)} 个）】")
        for m in misses:
            print(f"  p{m['page']:2d} {m['region_id']}: tiled_conf={m['tiled_conf']:.4f}  "
                  f"best_iou={m['iou']:.3f}  best_iou_conf={m.get('best_iou_conf', 0):.4f}  "
                  f"bbox={[int(x) for x in m['target_bbox']]}")

    # ---- 保存完整结果 ----
    result = {
        "experiment": "q1_conf_sweep_detect",
        "config_b": "main_chain_conf=0.3_no_tiling",
        "iou_threshold": IOU_THRESH,
        "targets_total": n_total,
        "hit_count": n_hit,
        "miss_count": n_miss,
        "hit_rate": n_hit / n_total,
        "hit_main_conf_stats": {
            "min": min(hit_confs) if hit_confs else None,
            "max": max(hit_confs) if hit_confs else None,
            "mean": sum(hit_confs) / len(hit_confs) if hit_confs else None,
            "below_0.7": sum(1 for c in hit_confs if c < 0.7),
            "between_0.7_0.8": sum(1 for c in hit_confs if 0.7 <= c < 0.8),
            "above_0.8": sum(1 for c in hit_confs if c >= 0.8),
        },
        "box_count_delta": {
            "total_a_main": total_a_main,
            "total_b": total_b,
            "delta": total_b - total_a_main,
            "per_page": page_deltas,
        },
        "hit_details": hit_results,
    }
    out_path = OUT_DIR / "q1_conf_sweep_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已保存: {out_path}")

    # ---- 结论提示 ----
    print(f"\n{'=' * 70}")
    if n_miss == 0:
        print("结论倾向：所有瓦片新增框都能被主链 conf=0.3 直接捞到 → 瓦片副引擎可能是冗余的")
    elif n_hit / n_total >= 0.8:
        print(f"结论倾向：{n_hit}/{n_total} 命中，大部分可被主链降 conf 覆盖 → 瓦片价值有限")
    else:
        print(f"结论倾向：仅 {n_hit}/{n_total} 命中，瓦片确实解决了部分分辨率问题 → 需进一步分析未命中框特征")
    print("下一步：对 B 组增量框跑 OCR，验证假框过滤效果")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
