"""在 86 个对齐的 detector crop 图上评测 OCR 引擎。

输入: output/data/eval_86.json (entries: crop图+GT内容+type)
引擎: local(For-Manga llama-server) | dashscope(qwen)
用法: python scripts/ocr_eval_86.py --engine local|dashscope --out <preds.json>
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from ocr_run import send_one, dashscope_ocr_batch  # noqa: E402


def run_local(crops, base_url="http://127.0.0.1:8118/v1", model="paddle"):
    out = []
    for c in crops:
        try:
            ocr = send_one(base_url, model, c)
        except Exception as e:
            ocr = f"<ERR:{type(e).__name__}>"
        out.append({"crop": os.path.abspath(c), "ocr": ocr})
        print(f"  {Path(c).name}: {ocr[:30]!r}", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["local", "dashscope"], required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    data = json.loads((ROOT / "output" / "data" / "eval_86.json").read_text(encoding="utf-8"))
    entries = data["entries"]
    crops = [e["crop"] for e in entries]
    print(f"[ocr_eval_86] {len(crops)} crops, engine={a.engine}", file=sys.stderr)

    if a.engine == "local":
        preds = run_local(crops, model=a.model or "paddle")
    else:
        preds = dashscope_ocr_batch(crops, model=a.model or "qwen-vl-ocr-latest")

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(preds, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ocr_eval_86] preds -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
