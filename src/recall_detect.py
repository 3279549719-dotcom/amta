"""Benchmark A recall 探测：对源图跑 4 detector，输出每页每个 engine 的原始框(未去重)。

recall 需要知道「每个 engine 检出了哪些框」去和 GT(整页枚举) 做 IoU 对齐。
输出 output/recall_detections.json:
  { "<page_key>": { "<engine>": [{node_id, bbox:[x0,y0,x1,y1], bubble_type}], ... }, ... }
用法: python src/recall_detect.py <src_dir>
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from koharu_client import KoharuClient, KoharuError  # noqa: E402
from pipeline import DETECTOR_STEPS  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "output"


def _bbox(block: dict) -> list[float]:
    t = block.get("transform", {})
    x = float(t.get("x", 0)); y = float(t.get("y", 0))
    w = float(t.get("w", t.get("width", 0))); h = float(t.get("h", t.get("height", 0)))
    return [round(x, 1), round(y, 1), round(x + w, 1), round(y + h, 1)]


def run_one(client: KoharuClient, page: Path, engine: str) -> list[dict]:
    proj = f"amta-rec-{uuid.uuid4().hex[:8]}"
    client.close_current_project()
    client.create_project(proj)
    try:
        page_id = client.import_page(page)
        op = client.run_pipeline(page_ids=[page_id], steps=DETECTOR_STEPS[engine])
        result = client.wait_operation(op, timeout=1200)
        if result.get("status") != "completed":
            raise KoharuError(f"{engine} failed: {result}")
        nodes = client.get_page_nodes(page_id)
        blocks = KoharuClient.collect_blocks(nodes)  # returns list[dict]
        return [{"node_id": b.get("node_id", ""), "bbox": _bbox(b), "bubble_type": b.get("bubble_type", ""),
                 "ocr": b.get("ocr", "")}
                for b in blocks]
    finally:
        client.close_current_project()


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
    out: dict[str, dict] = {}
    for idx, page in enumerate(pages):
        key = f"page_{idx}"
        out[key] = {"path": str(page), "engines": {}}
        for eng in DETECTOR_STEPS:
            print(f"[recall] {key} / {eng} ...", flush=True)
            try:
                out[key]["engines"][eng] = run_one(client, page, eng)
            except Exception as e:  # noqa: BLE001
                print(f"[recall] WARN {key} {eng}: {e}", flush=True)
                out[key]["engines"][eng] = []
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "recall_detections.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[recall] done -> {dest}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
