"""OCR 评测聚合：读 meta(crop→GT) + preds(crop→ocr)，用 metrics 算 CER/EM，分 4 类 + ALL。

用法:
  python scripts/ocr_eval.py --engine for_manga \
      --meta output/data/ocr_eval_meta.json \
      --preds output/data/preds_for_manga.json \
      --out output/data/benchmark_b_for_manga.json
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.metrics import cer  # noqa: E402

CLASSES = ["dialogue_in", "dialogue_out", "sfx", "bg_text"]


def _key(path):
    """crop 匹配键：取 basename，容忍相对/绝对路径差异。"""
    return os.path.basename(str(path))


def eval_rows(meta, preds):
    """meta: [{crop, content, type, ...}]; preds: [{crop, ocr}]. 返回 (rows, summary)。"""
    by_crop = {_key(p["crop"]): (p.get("ocr") or "") for p in preds}
    rows = []
    for m in meta:
        pred = by_crop.get(_key(m["crop"]), "")
        c = cer(m["content"], pred)
        em = 1 if c == 0.0 else 0
        rows.append({"crop": m["crop"], "type": m["type"], "gt": m["content"],
                     "pred": pred, "cer": c, "em": em})
    summary = {}
    for t in CLASSES + ["ALL"]:
        sub = rows if t == "ALL" else [r for r in rows if r["type"] == t]
        n = len(sub)
        summary[t] = {
            "n": n,
            "cer": round(sum(r["cer"] for r in sub) / n, 4) if n else 0.0,
            "em": round(sum(r["em"] for r in sub) / n, 4) if n else 0.0,
        }
    return rows, summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--preds", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    meta = json.loads(Path(a.meta).read_text(encoding="utf-8"))
    preds = json.loads(Path(a.preds).read_text(encoding="utf-8"))
    rows, summary = eval_rows(meta, preds)
    out = {"engine": a.engine, "summary": summary, "rows": rows}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[ocr_eval] -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
