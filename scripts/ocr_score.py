"""Benchmark B 评分：manga-ocr 识别结果 vs GT 内容，算 CER(字符错误率)+EM(完全匹配率)。

输入:
  output/ocr_result.json  (manga-ocr 每页识别 {bbox, ocr, confidence})
  output/recall_gt.json   (GT 内容清单)
输出:
  output/benchmark_b.json
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.metrics import cer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "data"


def main() -> int:
    ocr = json.loads((OUT / "ocr_result.json").read_text(encoding="utf-8"))
    gt_data = json.loads((OUT / "recall_gt.json").read_text(encoding="utf-8"))

    from collections import defaultdict
    # 每页: GT 条目 vs manga-ocr 输出, 贪心匹配(每个 GT 找 best 输出)
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
                if used[j]: continue
                sc = min(cer(gtext, p), cer(gtext, p))  # CER 越低越好
                if sc < best_score:
                    best_score, best_pred, best_j = sc, p, j
            if best_j >= 0:
                used[best_j] = True
            em = 1 if best_score == 0.0 else 0
            all_rows.append({"page": gkey, "type": region["type"], "gt": region["content"],
                             "pred": best_pred, "cer": round(best_score, 3), "em": em})

    # 汇总
    by_type = defaultdict(lambda: {"n": 0, "cer_sum": 0.0, "em": 0})
    for r in all_rows:
        t = r["type"]; by_type[t]["n"] += 1; by_type[t]["cer_sum"] += r["cer"]; by_type[t]["em"] += r["em"]
    summary = {}
    for t, v in by_type.items():
        summary[t] = {"n": v["n"], "cer": round(v["cer_sum"] / v["n"], 3) if v["n"] else 0,
                      "em": round(v["em"] / v["n"], 3) if v["n"] else 0}
    n = len(all_rows)
    summary["ALL"] = {"n": n, "cer": round(sum(r["cer"] for r in all_rows) / n, 3) if n else 0,
                      "em": round(sum(r["em"] for r in all_rows) / n, 3) if n else 0}

    result = {"engine": "manga-ocr", "summary": summary, "rows": all_rows}
    (OUT / "benchmark_b.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[bench_b] -> {OUT / 'benchmark_b.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
