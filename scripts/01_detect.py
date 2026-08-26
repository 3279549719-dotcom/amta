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
from amta.geometry import build_regions, flatten_regions, union_blocks  # noqa: E402

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
    # 每引擎 compact 成 {node_id, bubble_type, text} + bbox(下游依赖)
    comp = {eng: compact_blocks(blks, _FIELDS) for eng, blks in per_engine.items()}
    blocks = union_blocks(comp)  # IoU 去重并保留首个命中框元数据
    # 契约升级: 重组为 regions[].child_lines[].sub_tier(嵌套子框挂容器, 不丢弃)
    regions = build_regions(blocks)
    flat_blocks = flatten_regions(regions)  # 展平供 02_ocr 裁框(每 child_line 一框)

    doc = {
        "work_id": work_id,
        "page": raw_page.stem,
        "source": str(raw_page),
        "regions": regions,
        "blocks": flat_blocks,
        "n_boxes": len(flat_blocks),
        "n_regions": len(regions),
        "detect_steps": DETECT_STEPS,
        "per_engine_boxes": {eng: len(blks) for eng, blks in comp.items()},
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
