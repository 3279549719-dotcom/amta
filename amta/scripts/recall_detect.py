"""Benchmark A recall 探测：对源图跑 4 detector，输出每页每 engine 的原始框（未去重）。

recall 需要知道「每个 engine 检出了哪些框」去和 GT(整页枚举) 做 IoU 对齐。
输出 output/data/recall_detections.json:
  { "<page_key>": { path, engines: { "<engine>": [{node_id, bbox, bubble_type, ocr}], ... } }, ... }
用法: python scripts/recall_detect.py <src_dir> [max_pages]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.koharu_client import KoharuClient  # noqa: E402
from amta.paths import DATA, write_json  # noqa: E402
from amta.pipeline import DETECTOR_STEPS  # noqa: E402
from amta.runner import compact_blocks, run_all_pages  # noqa: E402

OUT = DATA / "recall_detections.json"


def _page_key(page: Path, idx: int) -> str:
    return f"page_{idx}"


def main(argv: list[str]) -> int:
    src = Path(argv[0])
    max_pages = int(argv[1]) if len(argv) > 1 else 10
    # 按文件名数字自然序（1.jpg,2.jpg,...,10.jpg），限前 max_pages 页
    pages = sorted(src.glob("*.jpg"), key=lambda p: int(p.stem))
    if not pages:
        pages = sorted(src.glob("*.jpeg"), key=lambda p: int(p.stem))
    pages = pages[:max_pages]
    print(f"[recall] {len(pages)} pages (limit={max_pages}), engines={list(DETECTOR_STEPS)}", flush=True)
    client = KoharuClient()
    client.wait_server()
    out = run_all_pages(client, pages, DETECTOR_STEPS, _page_key, prefix="amta-rec",
                        timeout=1200, label="recall")
    # 兼容旧输出形状：只留 {node_id, bbox, bubble_type, ocr}（下游 recall_crop 依赖 bbox）
    for entry in out.values():
        entry["engines"] = {eng: compact_blocks(blocks, ("node_id", "bubble_type", "ocr"))
                            for eng, blocks in entry["engines"].items()}
    write_json(OUT, out)
    print(f"[recall] done -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
