"""内容级 recall：GT 内容清单 vs detector 并集框识别内容，做匹配。

recall = GT 中「同页被 detector 识别文字覆盖」的条目 / GT 全部条目。
匹配：归一化后 GT 文字是识别文字的子串，或字符重合度高(>=0.6)。

输入:
  output/recall_gt.json            (GT: page_1.. 的内容+类型)
  output/recall_ocr.json           (detector 识别: {page_N: [{crop, text, empty}]})
输出:
  output/recall_result.json
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"


def norm(s: str) -> str:
    s = re.sub(r"[^\u3040-\u30ff\u4e00-\u9fffA-Za-z]", "", s or "")
    return s


def match_score(gt: str, det: str) -> float:
    g, d = norm(gt), norm(det)
    if not g or not d:
        return 0.0
    if g in d or d in g:
        return 1.0
    # 字符重合度
    inter = len(set(g) & set(d))
    return inter / max(len(set(g)), 1)


def main() -> int:
    gt_data = json.loads((OUT / "recall_gt.json").read_text(encoding="utf-8"))
    ocr_data = json.loads((OUT / "recall_ocr.json").read_text(encoding="utf-8"))

    # 建每页 detector 识别文字集合
    page_det_text: dict[str, list[str]] = {}
    for pkey, items in ocr_data.items():
        texts = [i.get("text", "") for i in items if not i.get("empty")]
        page_det_text[pkey] = texts

    # 匹配 GT
    from collections import Counter
    gt_tot = Counter(); gt_tp = Counter()
    pages_detail = {}
    for gkey, regions in gt_data["pages"].items():
        idx = int(gkey.split("_")[1]) - 1
        detkey = f"page_{idx}"
        det_texts = page_det_text.get(detkey, [])
        rows = []
        for region in regions:
            cls = region["type"]; content = region["content"]
            gt_tot[cls] += 1
            best = max((match_score(content, dt) for dt in det_texts), default=0.0)
            recalled = best >= 0.6
            if recalled:
                gt_tp[cls] += 1
            rows.append({"content": content, "type": cls, "match_score": round(best, 2),
                         "recalled": recalled, "best_det": best})
        pages_detail[gkey] = {"det_key": detkey, "regions": rows}

    all_classes = ["dialogue_in", "dialogue_out", "sfx", "bg_text"]
    summary = {}
    for cls in all_classes:
        t = gt_tot[cls]; tp = gt_tp[cls]
        summary[cls] = {"gt": t, "recalled": tp, "recall": round(tp / t, 3) if t else 0.0}
    total_gt = sum(gt_tot.values()); total_tp = sum(gt_tp.values())
    summary["ALL"] = {"gt": total_gt, "recalled": total_tp, "recall": round(total_tp / total_gt, 3) if total_gt else 0.0}

    result = {"method": "content-level recall", "summary": summary, "pages": pages_detail,
              "detected_frames": {k: len(v) for k, v in page_det_text.items()}}
    (OUT / "recall_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[recall_score] -> {OUT / 'recall_result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
