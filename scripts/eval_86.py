"""对 eval_86 的 entries + preds 算 CER/EM，分 4 类 + ALL。"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from amta.metrics import cer  # noqa: E402

CLASSES = ["dialogue_in", "dialogue_out", "sfx", "bg_text"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--preds", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    data = json.loads((ROOT / "output" / "data" / "eval_86.json").read_text(encoding="utf-8"))
    entries = data["entries"]
    preds = json.loads(Path(a.preds).read_text(encoding="utf-8"))
    by_crop = {os.path.basename(p["crop"]): (p.get("ocr") or "") for p in preds}

    rows = []
    for e in entries:
        pred = by_crop.get(os.path.basename(e["crop"]), "")
        c = cer(e["content"], pred)
        em = 1 if c == 0.0 else 0
        rows.append({"crop": os.path.basename(e["crop"]), "page": e["page"], "type": e["type"],
                     "gt": e["content"], "pred": pred, "cer": c, "em": em})

    summary = {}
    for t in CLASSES + ["ALL"]:
        sub = rows if t == "ALL" else [r for r in rows if r["type"] == t]
        n = len(sub)
        summary[t] = {"n": n,
                      "cer": round(sum(r["cer"] for r in sub) / n, 4) if n else 0.0,
                      "em": round(sum(r["em"] for r in sub) / n, 4) if n else 0.0}

    out = {"engine": a.engine, "summary": summary, "rows": rows,
           "unmatched": data["unmatched"]}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[eval_86] -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
