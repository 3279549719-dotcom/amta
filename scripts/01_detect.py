"""01_detect 工位 — 检测:raw 页 → artifacts/detection.json(per-work 契约,ADR-013)。

用法: python scripts/01_detect.py --work-id <id> --raw <page图> [--out <detection.json>]
输出: {work_id, page, source, blocks: [{node_id, bbox, bubble_type, text}], detect_steps}
断点: 输出文件已存在 → 跳过(00_run_all 调用方决定,本脚本只执行)

检测策略(修复 4-detector 并集,对齐评测 recall 0.98):
  01_detect 从单 detector(comic-text-detector) 改为跑全部 4 个 detector 并集 + IoU 去重,
  保持 blocks[] 扁平契约不变,下游 02_ocr/03 零改动(Phase A)。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.koharu_client import KoharuClient  # noqa: E402
from amta.paths import write_json  # noqa: E402
from amta.pipeline import DETECTOR_STEPS  # noqa: E402
from amta.runner import compact_blocks, run_all_pages  # noqa: E402
from amta.geometry import assign_category, mark_contained, union_blocks  # noqa: E402
# 回退用: build_regions / flatten_regions 仍在 geometry.py 中, 如需回退旧架构可重新 import
from PIL import Image  # noqa: E402

# 全部 4 个 detector 并集(评测召回 0.98 的配置),按文件内定义顺序稳定
DETECT_STEPS = list(DETECTOR_STEPS.keys())

# 保留字段(与旧单 detector 输出同形,下游 02_ocr 依赖 bbox)
_FIELDS = ("node_id", "bbox", "bubble_type", "text")


def run(work_id: str, raw_page: Path, out_path: Path,
        host: str = "127.0.0.1", port: int = 4000) -> dict:
    client = KoharuClient(host=host, port=port)
    client.wait_server(timeout=60)

    # 跑全部 4 个 detector(各自独立流水线,与评测 recall_detect 同构),再并集去重
    # run_all_pages 返回 {page_key: {"path", "engines": {engine: [blocks]}}}
    pages = sorted([raw_page], key=lambda p: p.name)
    results = run_all_pages(client, pages, DETECTOR_STEPS,
                            prefix="amta-det", timeout=1200, label="01_detect")
    per_engine = next(iter(results.values()))["engines"]
    # 每引擎 compact 成 {node_id, bubble_type, text} + bbox(下游依赖)，并注入引擎名溯源
    comp = {eng: compact_blocks(blks, _FIELDS, source_engine=eng)
            for eng, blks in per_engine.items()}
    blocks = union_blocks(comp)
    blocks = assign_category(blocks)  # Phase 1/ADR-019: bubble_type to 3-level category
    # Front3 Stage 1 (ADR-023): source_engines = 检出该框的 detector 引擎名列表(union 已注入)
    # 仅当 union 未注入时兜底空列表（不应再出现 node_id 伪引擎名）
    for b in blocks:
        if not isinstance(b.get("source_engines"), list):
            b["source_engines"] = []
    # Front3 Stage 1: 替代 absorb_contained — 标记嵌套但不丢弃, 所有框平级独立 OCR
    blocks = mark_contained(blocks)

    img = Image.open(raw_page)

    # Tracing: Stage 1 处理过程
    trace = {
        "page": raw_page.stem,
        "per_engine_raw": {eng: len(blks) for eng, blks in comp.items()},
        "after_union": len(union_blocks(comp)),
        "after_mark_contained": len(blocks),
        "contained_boxes": [b["region_id"] for b in blocks if b.get("contained_in")],
        "contained_pairs": [
            (b["region_id"], b["contained_in"]) for b in blocks if b.get("contained_in")
        ],
        "detect_steps": DETECT_STEPS,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    trace_path = out_path.parent / f"{raw_page.stem}_01_detect_trace.json"
    write_json(trace_path, trace)

    doc = {
        "work_id": work_id,
        "page": raw_page.stem,
        "source": str(raw_page),
        "image_meta": {"width": img.width, "height": img.height,
                       "channels": len(img.getbands())},
        "blocks": blocks,
        "n_boxes": len(blocks),
        "detect_steps": DETECT_STEPS,
        "per_engine_boxes": {eng: len(blks) for eng, blks in comp.items()},
        "front3_version": "2.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(out_path, doc)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="01_detect 工位")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--raw", required=True, type=Path, help="源页图路径")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    doc = run(a.work_id, a.raw, a.out)
    print(f"[01_detect] {doc['page']}: {doc['n_boxes']} boxes -> {a.out}")
    for eng, n in doc["per_engine_boxes"].items():
        print(f"  - {eng}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
