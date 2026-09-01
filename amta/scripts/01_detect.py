"""01_detect 工位 — 检测: raw 页 → artifacts/{page}_detection.json（薄 CLI）。

用法: python scripts/01_detect.py --work-id <id> --raw <page图> --out <detection.json> [--page-idx N] [--conf 0.3]
实现: RT-DETR-v2 ONNX 检测器（detect_rtdetr.RTDetrDetector），输出 label/score。
断点: 输出文件已存在 → 跳过(00_run_all 调用方决定,本脚本只执行)。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from detect_rtdetr import RTDetrDetector  # noqa: E402
from amta.paths import write_json  # noqa: E402


def detect_page(work_id: str, raw_page: Path, out_dir: Path, *,
                page_idx: int | None = None, conf_threshold: float = 0.5,
                out_path: Path | None = None) -> dict:
    """单页检测：RT-DETR-v2 → detection.json（doc 信封格式）。"""
    if page_idx is None:
        page_idx = int(raw_page.stem) - 1
    page = f"page_{page_idx}"

    det = RTDetrDetector(conf_threshold=conf_threshold)
    t0 = time.time()
    blocks = det.detect(str(raw_page))
    elapsed = time.time() - t0

    doc = {
        "work_id": work_id,
        "page": page,
        "source_engines": ["rtdetr-v2"],
        "n_boxes": len(blocks),
        "per_engine_boxes": {"rtdetr-v2": len(blocks)},
        "conf_threshold": conf_threshold,
        "elapsed_s": round(elapsed, 2),
        "blocks": blocks,
    }
    target = out_path or (out_dir / f"{page}_detection.json")
    write_json(target, doc)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="01_detect 工位（RT-DETR-v2）")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--raw", required=True, type=Path, help="源页图路径(N.jpg)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--page-idx", type=int, default=None,
                    help="0 基页号（默认从文件名 N.jpg 推导 N-1）")
    ap.add_argument("--conf", type=float, default=0.5, help="置信度阈值（默认 0.5，过滤低置信度假框）")
    a = ap.parse_args()
    doc = detect_page(a.work_id, a.raw, a.out.parent, page_idx=a.page_idx,
                      conf_threshold=a.conf, out_path=a.out)
    print(f"[01_detect] {doc['page']}: {doc['n_boxes']} boxes "
          f"(conf={a.conf}, {doc['elapsed_s']}s) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
