"""Benchmark B 评分：manga-ocr 识别结果 vs GT 内容，算 CER/EM（复用 amta.evalkit 聚合）。

输入:
  output/data/ocr_result.json  (manga-ocr 每页识别 {bbox, ocr, confidence})
  output/data/recall_gt.json   (GT 内容清单)
输出:
  output/data/benchmark_b.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.evalkit import summarize_rows  # noqa: E402
from amta.metrics import cer  # noqa: E402
from amta.paths import DATA, read_json, write_json  # noqa: E402


def main() -> int:
    ocr = read_json(DATA / "ocr_result.json")
    gt_data = read_json(DATA / "recall_gt.json")

    all_rows = []
    for gkey, regions in gt_data["pages"].items():
        idx = int(gkey.split("_")[1]) - 1
        okey = f"page_{idx}"
        preds = [(b.get("ocr") or "") for b in ocr.get(okey, {}).get("engines", {}).get("manga-ocr", [])]
        preds = [p for p in preds if p.strip()]
        used = [False] * len(preds)
        for region in regions:
            gtext = region["content"]
            best_score, best_pred, best_j = 1.0, "", -1
            for j, p in enumerate(preds):
                if used[j]:
                    continue
                sc = cer(gtext, p)  # CER 越低越好
                if sc < best_score:
                    best_score, best_pred, best_j = sc, p, j
            if best_j >= 0:
                used[best_j] = True
            all_rows.append({"page": gkey, "type": region["type"], "gt": region["content"],
                             "pred": best_pred, "cer": round(best_score, 3),
                             "em": 1 if best_score == 0.0 else 0})

    summary = summarize_rows(all_rows)
    result = {"engine": "manga-ocr", "summary": summary, "rows": all_rows}
    write_json(DATA / "benchmark_b.json", result)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[bench_b] -> {DATA / 'benchmark_b.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
