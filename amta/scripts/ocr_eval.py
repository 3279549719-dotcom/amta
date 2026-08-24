"""OCR 评测聚合：读 meta(crop→GT) + preds(crop→ocr)，用 amta.evalkit 算 CER/EM，分 4 类 + ALL。

用法:
  python scripts/ocr_eval.py --engine for_manga \
      --meta output/data/ocr_eval_meta.json \
      --preds output/data/preds_for_manga.json \
      --out output/data/benchmark_b_for_manga.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.evalkit import TEXT_CLASSES, eval_rows  # noqa: E402
from amta.paths import read_json, write_json  # noqa: E402

__all__ = ["eval_rows", "TEXT_CLASSES"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--preds", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    meta = read_json(a.meta)
    preds = read_json(a.preds)
    rows, summary = eval_rows(meta, preds)
    out = {"engine": a.engine, "summary": summary, "rows": rows}
    write_json(a.out, out)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[ocr_eval] -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
