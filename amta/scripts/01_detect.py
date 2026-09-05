"""01_detect 工位 CLI — 检测: raw 页 → artifacts/{page}_detection.json（薄包装）。

实现已移至 src/amta/detect_station.py，本脚本只保留 CLI 入口。
用法: python scripts/01_detect.py --work-id <id> --raw <page图> --out <detection.json> [--page-idx N] [--conf 0.7]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.detect_station import detect_page  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="01_detect 工位（RT-DETR-v2）")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--raw", required=True, type=Path, help="源页图路径(N.jpg)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--page-idx", type=int, default=None,
                    help="页号（1 基，默认从文件名 N.jpg 推导 N）")
    ap.add_argument("--conf", type=float, default=0.7, help="置信度阈值（默认 0.7）")
    a = ap.parse_args()
    doc = detect_page(a.work_id, a.raw, a.out.parent, page_idx=a.page_idx,
                      conf_threshold=a.conf, out_path=a.out)
    print(f"[01_detect] {doc['page']}: {doc['n_boxes']} boxes "
          f"(conf={a.conf}, {doc['elapsed_s']}s) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
