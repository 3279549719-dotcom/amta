"""SFX 三路 OCR 对比：manga-ocr / mit48px / baberu vs GT SFX 内容，算 CER/EM。

输入:
  output/ocr_result.json    (koharu manga-ocr + mit48px 整页 detector 框输出)
  output/baberu_smoke.json  (baberu 对 recall_crops 的输出)
  output/recall_gt.json     (GT SFX 内容)
输出:
  output/benchmark_b_sfx.json
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"


def norm(s: str) -> str:
    return re.sub(r"[^\u3040-\u30ff\u4e00-\u9fffA-Za-z0-9]", "", s or "")


def levenshtein(a, b):
    a, b = norm(a), norm(b)
    if not a: return len(b)
    if not b: return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j-1] + 1, prev[j-1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(gt, pred):
    a, b = norm(gt), norm(pred)
    if not a and not b: return 0.0
    if not a: return 1.0
    return levenshtein(a, b) / max(len(a), 1)


def best_match(gt_text, pred_list):
    best = 1.0; best_p = ""
    for p in pred_list:
        sc = cer(gt_text, p)
        if sc < best:
            best, best_p = sc, p
    return best, best_p


def main() -> int:
    ocr = json.loads((OUT / "ocr_result.json").read_text(encoding="utf-8"))
    bab = json.loads((OUT / "baberu_smoke.json").read_text(encoding="utf-8"))
    gt_data = json.loads((OUT / "recall_gt.json").read_text(encoding="utf-8"))

    rows = []
    for gkey, regions in gt_data["pages"].items():
        idx = int(gkey.split("_")[1]) - 1
        okey = f"page_{idx}"
        sfx = [r for r in regions if r["type"] == "sfx"]
        if not sfx: continue
        # manga-ocr 该页所有输出(做匹配池)
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

    # 汇总
    import statistics
    out = {"engine": "sfx-3way", "n_sfx": len(rows), "rows": rows}
    for eng in ["manga", "mit48px", "baberu"]:
        cers = [r[eng]["cer"] for r in rows]
        em = sum(1 for r in rows if r[eng]["cer"] == 0)
        out[f"{eng}_summary"] = {"cer": round(statistics.mean(cers), 3) if cers else 0,
                                 "em": round(em / len(rows), 3) if rows else 0}
    (OUT / "benchmark_b_sfx.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== SFX 三路 OCR 对比 ===")
    for eng in ["manga", "mit48px", "baberu"]:
        s = out[f"{eng}_summary"]
        print(f"  {eng}: CER={s['cer']} EM={s['em']}")
    print(f"-> {OUT / 'benchmark_b_sfx.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
