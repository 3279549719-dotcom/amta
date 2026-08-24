"""SFX 三路 OCR 对比：manga-ocr / mit48px / baberu vs GT SFX 内容，算 CER/EM。

输入:
  output/data/ocr_result.json        (koharu manga-ocr + mit48px 整页 detector 框输出)
  output/data/baberu_result.json     (baberu 对 recall_crops 的输出)
  output/data/recall_gt.json         (GT SFX 内容)
输出:
  output/data/benchmark_b_sfx.json
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.metrics import best_match  # noqa: E402
from amta.paths import DATA, read_json, write_json  # noqa: E402


def main() -> int:
    ocr = read_json(DATA / "ocr_result.json")
    bab = read_json(DATA / "baberu_result.json")
    gt_data = read_json(DATA / "recall_gt.json")

    rows = []
    for gkey, regions in gt_data["pages"].items():
        idx = int(gkey.split("_")[1]) - 1
        okey = f"page_{idx}"
        sfx = [r for r in regions if r["type"] == "sfx"]
        if not sfx:
            continue
        # manga-ocr 该页所有输出（做匹配池）
        manga_preds = [(b.get("ocr") or "") for b in ocr.get(okey, {}).get("engines", {}).get("manga-ocr", [])]
        mit_preds = [(b.get("ocr") or "") for b in ocr.get(okey, {}).get("engines", {}).get("mit48px-ocr", [])]
        # baberu 对 page_{idx}_uXX crops 的输出
        bab_preds = [v for k, v in bab.items() if k.startswith(okey + "_u") and not str(v).startswith("__ERROR")]
        for r in sfx:
            gtext = r["content"]
            m_cer, m_p = best_match(gtext, manga_preds)
            mi_cer, mi_p = best_match(gtext, mit_preds)
            b_cer, b_p = best_match(gtext, bab_preds)
            rows.append({"page": gkey, "gt": gtext,
                         "manga": {"pred": m_p, "cer": round(m_cer, 3)},
                         "mit48px": {"pred": mi_p, "cer": round(mi_cer, 3)},
                         "baberu": {"pred": b_p, "cer": round(b_cer, 3)}})

    out = {"engine": "sfx-3way", "n_sfx": len(rows), "rows": rows}
    for eng in ("manga", "mit48px", "baberu"):
        cers = [r[eng]["cer"] for r in rows]
        em = sum(1 for r in rows if r[eng]["cer"] == 0)
        out[f"{eng}_summary"] = {"cer": round(statistics.mean(cers), 3) if cers else 0,
                                 "em": round(em / len(rows), 3) if rows else 0}
    write_json(DATA / "benchmark_b_sfx.json", out)
    print("=== SFX 三路 OCR 对比 ===")
    for eng in ("manga", "mit48px", "baberu"):
        s = out[f"{eng}_summary"]
        print(f"  {eng}: CER={s['cer']} EM={s['em']}")
    print(f"-> {DATA / 'benchmark_b_sfx.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
