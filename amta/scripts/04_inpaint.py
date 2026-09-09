"""04_inpaint 工位 CLI — detection.json + raw 页 → clean 图 + inpaint 产物（薄包装）。

实现已移至 src/amta/inpaint_station.py（本地 lama-manga，ADR-029），本脚本只保留 CLI 入口。
用法: python scripts/04_inpaint.py --work-id <id> --det <detection.json> --raw <page图>
      --out <page>_inpaint.json --clean-dir <artifacts/clean> [--dry-run] [--refine-mask]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.inpaint.inpaint_station import run  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="04_inpaint 工位（本地 lama-manga）")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--det", required=True, type=Path)
    ap.add_argument("--raw", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--clean-dir", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refine-mask", action="store_true",
                    help="框内传统方法精修像素级 mask (Plan A)")
    ap.add_argument("--engine", default="lama-manga", choices=["lama-manga"],
                    help="inpaint 引擎（默认 lama-manga，本地推理）")
    a = ap.parse_args()
    doc = run(a.work_id, a.det, a.raw, a.out, clean_dir=a.clean_dir,
              dry_run=a.dry_run, refine_mask=a.refine_mask, inpaint_engine=a.engine)
    print(f"[04_inpaint] {doc['page']}: filled={doc['checks']['filled']} "
          f"inpainted={doc['checks']['inpainted']} skipped={doc['checks']['skipped']} "
          f"refine={doc['checks']['refine_mask']} engine={doc['checks']['inpaint_engine']} "
          f"diff={doc['checks']['pixel_diff_ratio']} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
