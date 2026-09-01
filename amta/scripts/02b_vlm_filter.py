"""02b VLM 三态过滤 — 读 canon → vlm_filter_v2(keep/fix/drop) → 输出过滤后的 canon。

照抄 run_full_pipeline_p14p18.py 的 Step 4 流程。
在规则过滤之后、翻译之前执行。
用法: python scripts/02b_vlm_filter.py --canon <canon.json> --raw <raw.jpg> --out <filtered_canon.json>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.artifacts import load_canon, stamp  # noqa: E402
from amta.paths import write_json  # noqa: E402
from amta.vlm_filter import vlm_filter_v2  # noqa: E402


def canon_to_blocks(canon_doc: dict) -> list[dict]:
    """照抄 run_full_pipeline_p14p18.py: Convert canon items to blocks for vlm_filter."""
    items = canon_doc.get("items", [])
    blocks = []
    for i, item in enumerate(items):
        text = item.get("baberu_text", "") or item.get("text", "")
        bbox = item.get("bbox", [0, 0, 0, 0])
        blocks.append({
            "bbox": bbox,
            "text": text,
            "region_id": item.get("region_id", f"r{i:02d}"),
            "bubble_type": item.get("bubble_type", "unknown"),
            "_idx": i,
            "_original_item": item,  # 保留原始 item 用于重建 canon
        })
    return blocks


def build_canon_from_blocks(filtered_blocks: list[dict], canon_doc: dict) -> dict:
    """照抄 run_full_pipeline_p14p18.py: Build canon items from filtered blocks."""
    # 从原始 items 获取 page（整数），不用顶层 doc 的 page（字符串 "page_0"）
    original_items = canon_doc.get("items", [])
    page = original_items[0].get("page", 0) if original_items else 0
    items = []
    for i, b in enumerate(filtered_blocks):
        original = b.get("_original_item", {})
        items.append({
            "region_id": original.get("region_id", f"r{i:02d}"),
            "bbox": b["bbox"],
            "text": b.get("text", ""),  # VLM fix 后可能已修正
            "baberu_text": b.get("text", ""),  # 用修正后的文本作为 baberu_text
            "original_text": b.get("original_text"),  # VLM fix 前的原文（仅 fix 时有）
            "page": page,
            "bubble_type": b.get("bubble_type", "unknown"),
            "vlm_state": b.get("filter_reason", "keep"),
            "source_engines": original.get("source_engines", ["rtdetr-v2", "baberu"]),
        })
        # 保留原始 item 中的其他字段
        for k, v in original.items():
            if k not in items[-1] and k not in ("text", "baberu_text"):
                items[-1][k] = v
    return items


def run(canon_path: str | Path, raw_path: str | Path, out_path: str | Path,
        work_id: str | None = None) -> dict:
    """读 canon → VLM 三态过滤 → 输出过滤后的 canon。"""
    canon_doc = load_canon(canon_path)
    blocks = canon_to_blocks(canon_doc)
    print(f"[02b_vlm_filter] input: {len(blocks)} blocks")

    kept, fixed, dropped = vlm_filter_v2(Path(raw_path), blocks)
    final_blocks = kept + fixed
    print(f"[02b_vlm_filter] keep={len(kept)}, fix={len(fixed)}, drop={len(dropped)}, final={len(final_blocks)}")

    filtered_items = build_canon_from_blocks(final_blocks, canon_doc)
    page = filtered_items[0].get("page", 0) if filtered_items else 0
    doc = stamp({
        "items": filtered_items,
        "n_regions": len(filtered_items),
        "vlm_filter": {
            "keep": len(kept),
            "fix": len(fixed),
            "drop": len(dropped),
            "dropped_regions": [
                {"region_id": b.get("region_id"), "text": b.get("text", "")[:30],
                 "reason": b.get("filter_reason")}
                for b in dropped
            ],
            "fixed_regions": [
                {"region_id": b.get("region_id"),
                 "original": b.get("original_text", "")[:30],
                 "corrected": b.get("text", "")[:30],
                 "reason": b.get("filter_reason")}
                for b in fixed
            ],
        },
    }, work_id or canon_doc.get("work_id", ""), page)

    write_json(Path(out_path), doc)
    print(f"[02b_vlm_filter] -> {out_path}")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canon", required=True, help="canon.json 路径")
    ap.add_argument("--raw", required=True, help="原始页面图片路径")
    ap.add_argument("--out", required=True, help="输出过滤后的 canon.json 路径")
    ap.add_argument("--work-id", default=None)
    a = ap.parse_args()
    run(a.canon, a.raw, a.out, work_id=a.work_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
