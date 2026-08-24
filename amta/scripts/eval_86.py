"""对 eval_86 的 entries + preds 算 CER/EM，分 4 类 + ALL（基于 amta.evalkit）。

输入: output/data/eval_86.json (entries: crop图 + GT内容 + type)
输出: --out <preds 评测结果 json>
用法: python scripts/eval_86.py --engine <name> --preds <preds.json> --out <result.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.evalkit import basename_key, eval_rows  # noqa: E402
from amta.paths import DATA, ensure_utf8_stdio, read_json, write_json  # noqa: E402

ensure_utf8_stdio()

EVAL_86 = DATA / "eval_86.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--preds", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    data = read_json(EVAL_86)
    entries = data["entries"]
    preds = read_json(a.preds)
    rows, summary = eval_rows(entries, preds)
    # 兼容旧输出：crop 用 basename，并补 page 字段
    page_by_crop = {basename_key(e["crop"]): e.get("page", "") for e in entries}
    for r in rows:
        r["crop"] = basename_key(r["crop"])
        r["page"] = page_by_crop.get(r["crop"], "")

    out = {"engine": a.engine, "summary": summary, "rows": rows,
           "unmatched": data["unmatched"]}
    write_json(a.out, out)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[eval_86] -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
