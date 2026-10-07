"""探针（只读）：竖排列数到底该由什么决定。

假设 H1：原图里是**一列**的气泡，译文就不该被切成多列（哪怕字号要降到下限）。
本探针度量：全部已产出片区中，若强制「一列 + 下限字号」，

  - 有多少片区在几何上放得下（放不下 = 一列确实不可能，多列是被迫的）
  - 放不下的片区，一列需要多少高度 / 可用多少高度（差多少）

从而区分两类多列：**被迫多列**（一列不可能）与**选择多列**（一列可以，只是字号小）。

用法：
  uv run python scripts/probes/check_one_column.py --work-id book-6e0926cdd8717137 --pages 2-20,33
  uv run python scripts/probes/check_one_column.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from PIL import ImageFont  # noqa: E402

from amta.typeset.typeset_engine import (  # noqa: E402
    MIN_SIZE,
    MIN_SIZE_RATIO,
    _cell_count,
    _font_metrics,
)


def one_col_feasible(text, font_path, bbox, size, ratio=0.85):
    x1, y1, x2, y2 = bbox
    font = ImageFont.truetype(str(font_path), size)
    char_w, line_h = _font_metrics(font)
    rows = _cell_count(text)
    need_h = rows * line_h
    budget_h = (y2 - y1) * ratio
    budget_w = (x2 - x1) * ratio
    return need_h <= budget_h and char_w <= budget_w, need_h, budget_h, char_w, budget_w


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-id")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--pages", default="")
    args = ap.parse_args()

    pages = []
    for part in args.pages.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    if not pages:
        pages = list(range(1, 101))

    works = []
    if args.all:
        works = [p.parents[1] for p in sorted((REPO / "workspace").glob("*/artifacts/typeset"))]
    elif args.work_id:
        works = [REPO / "workspace" / args.work_id]

    stats = {"n": 0, "delivered_multi": 0, "forced_multi": 0, "chosen_multi": 0}
    chosen = []
    for work in works:
        for p in pages:
            cp = work / "artifacts" / "canon" / f"page_{p}.json"
            tp = work / "artifacts" / "typeset" / f"page_{p}.json"
            if not cp.exists() or not tp.exists():
                continue
            try:
                canon = json.loads(cp.read_text(encoding="utf-8"))
                ts = json.loads(tp.read_text(encoding="utf-8"))
            except Exception:
                continue
            bb = {r.get("region_id"): r.get("bbox") for r in canon.get("items", [])}
            for it in ts.get("rendered_items", []):
                if it.get("layout_direction") != "vertical":
                    continue
                bbox = bb.get(it.get("region_id"))
                text = "".join(it.get("lines", []))
                fp = Path(it.get("font_path") or "")
                if not bbox or not text or not fp.name or not fp.exists():
                    continue
                cols = len(it.get("lines", []))
                size = int(it.get("font_size") or MIN_SIZE)
                stats["n"] += 1
                base = max(MIN_SIZE, int(size * MIN_SIZE_RATIO))
                ok, need_h, bud_h, cw, bud_w = one_col_feasible(text, fp, bbox, base)
                if cols > 1:
                    stats["delivered_multi"] += 1
                    if ok:
                        stats["chosen_multi"] += 1
                        chosen.append((work.name, p, it.get("region_id"), base,
                                       _cell_count(text), round(need_h, 1), round(bud_h, 1),
                                       cols, size, round(bud_w, 1), round(cw, 1)))
                    else:
                        stats["forced_multi"] += 1
    print(json.dumps(stats, ensure_ascii=True))
    print("work,page,rid,base_size,cells,need_h,budget_h,delivered_cols,delivered_size,budget_w,char_w")
    for c in chosen:
        print(",".join(str(x) for x in c))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
