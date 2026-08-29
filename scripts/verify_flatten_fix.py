"""验证 flatten_regions 残差保底修复效果 — 用已有的 detection.json（含 regions）重新展平，
对比修复前后 14.jpg/15.jpg 的输出框数和漏检区域覆盖情况。

用法: python scripts/verify_flatten_fix.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.regions import flatten_regions  # noqa: E402

ARTIFACTS = Path(r"E:\manga translator agent\amta\workspace\touhou-single-wing\artifacts")

# 已知漏检区域（label, page_file, expected_bbox, description）
MISS_CASES = [
    {
        "label": "15.jpg 左下 弟子だからね (大字主台词)",
        "page_file": "page_14_detection.json",  # page_14 = 15.jpg
        "expected_bbox": [50, 2430, 210, 2870],
        "old_only_narrow": [145, 2395, 197, 2698],  # 修复前只有这个 52px 窄条
    },
    {
        "label": "14.jpg 右下 では豊ちゃん… (大字长句)",
        "page_file": "page_13_detection.json",  # page_13 = 14.jpg
        "expected_bbox": [1600, 2630, 1870, 3150],
        "old_only_narrow": [1607, 2783, 1653, 3113],  # 修复前只有这个 46px 窄条
    },
]


def bbox_center(bbox):
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def bbox_area(bbox):
    return max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = bbox_area(a) + bbox_area(b) - inter
    return inter / ua if ua > 0 else 0


def old_flatten(regions):
    """修复前的旧逻辑：容器自身不输出，只输出 child_lines。"""
    out = []
    for r in regions:
        if r.get("child_lines"):
            for line in r["child_lines"]:
                out.append(dict(line))
        else:
            out.append(dict(r))
    return out


def check_coverage(blocks, expected_bbox, label):
    """检查预期区域是否有框覆盖（中心点在预期区域内 或 IoU > 0.1）。"""
    exp_cx, exp_cy = bbox_center(expected_bbox)
    hits = []
    for b in blocks:
        bb = b["bbox"]
        cx, cy = bbox_center(bb)
        center_in = expected_bbox[0] <= cx <= expected_bbox[2] and expected_bbox[1] <= cy <= expected_bbox[3]
        sc = iou(bb, expected_bbox)
        if center_in or sc > 0.1:
            hits.append({"bbox": bb, "w": bb[2] - bb[0], "h": bb[3] - bb[1],
                         "iou": round(sc, 3), "center_in": center_in,
                         "fallback": b.get("fallback_triggered", False)})
    return hits


def main():
    print("=" * 80)
    print("flatten_regions 残差保底修复验证")
    print("=" * 80)

    for case in MISS_CASES:
        path = ARTIFACTS / case["page_file"]
        if not path.exists():
            print(f"\n[SKIP] {case['label']} — 文件不存在: {path}")
            continue

        with open(path, encoding="utf-8") as f:
            doc = json.load(f)

        regions = doc["regions"]
        old_blocks = old_flatten(regions)
        new_blocks = flatten_regions(regions)

        print(f"\n{'─' * 80}")
        print(f"Case: {case['label']}")
        print(f"  文件: {path.name} (source={doc['source']})")
        print(f"  regions 数: {len(regions)}")
        print(f"  修复前 blocks 数: {len(old_blocks)}")
        print(f"  修复后 blocks 数: {len(new_blocks)}")
        print(f"  框数变化: {len(old_blocks)} → {len(new_blocks)} (+{len(new_blocks) - len(old_blocks)})")

        # 检查漏检区域覆盖
        print(f"\n  漏检区域覆盖检查 (expected_bbox={case['expected_bbox']}):")
        old_hits = check_coverage(old_blocks, case["expected_bbox"], case["label"])
        new_hits = check_coverage(new_blocks, case["expected_bbox"], case["label"])

        print(f"    修复前覆盖框数: {len(old_hits)}")
        for h in old_hits:
            print(f"      bbox={h['bbox']} w={h['w']:.0f} h={h['h']:.0f} iou={h['iou']} center_in={h['center_in']}")

        print(f"    修复后覆盖框数: {len(new_hits)}")
        for h in new_hits:
            print(f"      bbox={h['bbox']} w={h['w']:.0f} h={h['h']:.0f} iou={h['iou']} center_in={h['center_in']} fallback={h['fallback']}")

        # 判定
        old_max_w = max((h["w"] for h in old_hits), default=0)
        new_max_w = max((h["w"] for h in new_hits), default=0)
        exp_w = case["expected_bbox"][2] - case["expected_bbox"][0]

        print("\n  判定:")
        print(f"    预期区域宽度: {exp_w:.0f}px")
        print(f"    修复前最大覆盖框宽: {old_max_w:.0f}px ({'窄条，大字漏检' if old_max_w < exp_w * 0.5 else 'OK'})")
        print(f"    修复后最大覆盖框宽: {new_max_w:.0f}px ({'容器保底，大字被覆盖' if new_max_w >= exp_w * 0.5 else '仍漏检'})")

        if new_hits and any(h["fallback"] for h in new_hits):
            print("    ✓ 触发残差保底（fallback_triggered=True），母体容器被保留")
        elif new_max_w >= exp_w * 0.5:
            print("    ✓ 大字区域被覆盖（可能原本就有宽框）")
        else:
            print("    ✗ 仍存在漏检")

    # 全本统计：修复前后框数变化
    print(f"\n{'=' * 80}")
    print("全本框数统计（所有 detection.json）")
    print("=" * 80)
    total_old = 0
    total_new = 0
    fallback_count = 0
    pages_affected = []

    for path in sorted(ARTIFACTS.glob("page_*_detection.json")):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        regions = doc.get("regions")
        if regions is None:
            # 旧版本产物无 regions 字段，跳过
            continue
        old_blocks = old_flatten(regions)
        new_blocks = flatten_regions(regions)
        n_fb = sum(1 for b in new_blocks if b.get("fallback_triggered"))
        total_old += len(old_blocks)
        total_new += len(new_blocks)
        fallback_count += n_fb
        if len(new_blocks) != len(old_blocks) or n_fb > 0:
            pages_affected.append((path.name, doc.get("page", "?"), len(old_blocks), len(new_blocks), n_fb))

    print(f"  总页数: {len(list(ARTIFACTS.glob('page_*_detection.json')))}")
    print(f"  修复前总框数: {total_old}")
    print(f"  修复后总框数: {total_new}")
    print(f"  框数净增: +{total_new - total_old}")
    print(f"  触发保底的框数: {fallback_count}")
    print(f"  受影响页数: {len(pages_affected)}")
    if pages_affected:
        print("\n  受影响页面明细:")
        for name, page, old_n, new_n, fb in pages_affected:
            print(f"    {name} (page={page}): {old_n} → {new_n} (+{new_n - old_n}), fallback={fb}")

    print(f"\n{'=' * 80}")
    print("验证完成")
    print("=" * 80)


if __name__ == "__main__":
    main()
