"""01_detect 工位 — 检测:raw 页 → artifacts/detection.json(per-work 契约,ADR-013)。

用法: python scripts/01_detect.py --work-id <id> --raw <page图> [--out <detection.json>]
输出: {work_id, page, source, blocks: [{node_id, bbox, bubble_type, text}]}
断点: 输出文件已存在 → 跳过(00_run_all 调用方决定,本脚本只执行)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.koharu_client import KoharuClient  # noqa: E402
from amta.paths import write_json  # noqa: E402
from amta.runner import run_pipeline_once  # noqa: E402

# 工位收敛:漫画专用检测器(ADR-011 单引擎定案同思路)
DETECT_STEPS = ["comic-text-detector"]

_FIELDS = ("node_id", "bbox", "bubble_type", "text")


def run(work_id: str, raw_page: Path, out_path: Path,
        host: str = "127.0.0.1", port: int = 4000) -> dict:
    client = KoharuClient(host=host, port=port)
    client.wait_server(timeout=60)
    blocks = run_pipeline_once(client, raw_page, DETECT_STEPS)
    from amta.runner import compact_blocks
    blocks = compact_blocks(blocks, _FIELDS)
    doc = {
        "work_id": work_id,
        "page": raw_page.stem,
        "source": str(raw_page),
        "blocks": blocks,
        "n_boxes": len(blocks),
        "detect_steps": DETECT_STEPS,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
