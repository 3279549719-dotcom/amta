"""01_detect 工位 — 检测: raw 页 → artifacts/{page}_detection.json（薄 CLI）。

用法: python scripts/01_detect.py --work-id <id> --raw <page图> --out <detection.json> [--page-idx N]
实现: amta.detect_station.detect_page（4-detector 并集 + 嵌套标记 + region_id 单空间）。
断点: 输出文件已存在 → 跳过(00_run_all 调用方决定,本脚本只执行)。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.detect_station import detect_page  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="01_detect 工位")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--raw", required=True, type=Path, help="源页图路径(N.jpg)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--page-idx", type=int, default=None,
                    help="0 基页号（默认从文件名 N.jpg 推导 N-1）")
    a = ap.parse_args()
    doc = detect_page(a.work_id, a.raw, a.out.parent, page_idx=a.page_idx,
                      out_path=a.out)
    print(f"[01_detect] {doc['page']}: {doc['n_boxes']} boxes -> {a.out}")
    for eng, n in doc["per_engine_boxes"].items():
        print(f"  - {eng}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
