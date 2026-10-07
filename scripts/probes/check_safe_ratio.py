"""探针（只读）：SAFE_RATIO 到底挡掉了什么。

对一批已产出的 typeset 片区，用真实 bbox + 冻结译文，逐字号枚举竖排
(字号 × 列数) 的可行域，回答：

1. ratio=1.0（用满 bbox）是否存在「一列整句」的解？字号多大？
2. ratio=0.85（现行）同一片区的最大字号解是几列？差在宽还是高？
3. 全语料：0.85 相对 1.0 额外制造了多少个「被迫多列」的片区？
4. 「列数最少优先」是否能同时拿到最大字号（即两者是否真冲突）。

不改生产代码，不写文件。

用法：
  uv run python scripts/probes/check_safe_ratio.py --work-id book-6e0926cdd8717137 --pages 2-20,33
  uv run python scripts/probes/check_safe_ratio.py --all --only-multi
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PIL import ImageFont  # noqa: E402

from amta.typeset.typeset_engine import (  # noqa: E402
    MAX_SIZE,
    MIN_SIZE,
    _cell_count,
    _cell_rows,
    _column_width,
    _font_metrics,
    _fits,
)


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def enumerate_vertical(text: str, font_path: Path, bbox: list, ratio: float):
    """枚举 (字号 × 列数) 可行域。

    返回 dict：max_size_any_cols / max_size_1col / cols_at_max / diag。
    """
    x1, y1, x2, y2 = bbox
    w = (x2 - x1) * ratio
    h = (y2 - y1) * ratio
    cells = _cell_rows(text)
    n = len(cells)
    max_any = None   # (size, n_cols, cols, diag)
    max_one = None   # (size, cols, diag)
    for size in range(MIN_SIZE, MAX_SIZE + 1):
        font = ImageFont.truetype(str(font_path), size)
        char_w, line_h = _font_metrics(font)
        for n_cols in range(1, n + 1):
            base, extra = divmod(n, n_cols)
            cols, i = [], 0
            for k in range(n_cols):
                take = base + (1 if k < extra else 0)
                if take <= 0:
                    continue
                cols.append("".join(t for _kind, t in cells[i:i + take]))
                i += take
            rows = max((_cell_count(c) for c in cols), default=0)
            total_w = sum(_column_width(c, char_w, font) for c in cols)
            if total_w > w:
                break  # 列更多只会更宽
            if rows * line_h <= h:
                diag = {
                    "need_w": round(total_w, 2), "budget_w": round(w, 2),
                    "need_h": round(rows * line_h, 2), "budget_h": round(h, 2),
                }
                if max_any is None or size > max_any[0]:
                    max_any = (size, len(cols), cols, diag)
                if n_cols == 1 and (max_one is None or size > max_one[0]):
                    max_one = (size, cols, diag)
                break
    return {"max_any": max_any, "max_one": max_one,
            "w": round(w, 2), "h": round(h, 2), "n_cells": n}


def collect(work: Path, pages: list[int]) -> list[dict]:
    rows = []
    for p in pages:
        canon_p = work / "artifacts" / "canon" / f"page_{p}.json"
        ts_p = work / "artifacts" / "typeset" / f"page_{p}.json"
        if not canon_p.exists() or not ts_p.exists():
            continue
        canon = load_json(canon_p)
        ts = load_json(ts_p)
        bboxes = {r["region_id"]: r["bbox"] for r in canon.get("items", [])}
        for it in ts.get("rendered_items", []):
            rid = it["region_id"]
            if it.get("layout_direction") != "vertical":
                continue
            bbox = bboxes.get(rid)
            text = "".join(it.get("lines", []))
            if not bbox or not text:
                continue
            font_path = Path(it.get("font_path") or "")
            if not font_path.name or not font_path.exists():
                continue
            rows.append({
                "work": work.name, "page": p, "rid": rid, "bbox": bbox,
                "text": text, "cells": _cell_count(text),
                "delivered_size": it.get("font_size"),
                "delivered_cols": len(it.get("lines", [])),
                "r085": enumerate_vertical(text, font_path, bbox, 0.85),
                "r100": enumerate_vertical(text, font_path, bbox, 1.0),
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-id")
    ap.add_argument("--all", action="store_true", help="扫描所有 workspace/*/artifacts/typeset")
    ap.add_argument("--pages", default="", help="如 2-20,33")
    ap.add_argument("--only-multi", action="store_true",
                    help="只报告 0.85 多列而 1.0 可一列的片区")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    pages: list[int] = []
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

    works: list[Path] = []
    if args.all:
        works = sorted((REPO / "workspace").glob("*/artifacts/typeset"))
        works = [w.parents[1] for w in works]
    elif args.work_id:
        works = [REPO / "workspace" / args.work_id]

    rows: list[dict] = []
    for w in works:
        rows.extend(collect(w, pages))

    forced = [r for r in rows
              if r["r085"]["max_any"] and r["r100"]["max_any"]
              and r["r085"]["max_any"][1] > 1 and r["r100"]["max_any"][1] == 1]
    one_at_085 = [r for r in rows if r["r085"]["max_one"]]
    same_size = [r for r in rows
                 if r["r085"]["max_any"] and r["r085"]["max_one"]
                 and r["r085"]["max_any"][0] == r["r085"]["max_one"][0]]

    print("=== SUMMARY ===")
    print(f"workspaces / vertical regions : {len(works)} / {len(rows)}")
    print(f"0.85 有『一列整句』解         : {len(one_at_085)}")
    print(f"0.85 最大字号解本来就是 1 列  : {len(same_size)}")
    print(f"0.85 多列、1.0 可一列(被迫)   : {len(forced)}")
    print(f"0.85 多列 且 1.0 也最多多列   : "
          f"{sum(1 for r in rows if r['r085']['max_any'] and r['r085']['max_any'][1] > 1 and not (r['r100']['max_any'] and r['r100']['max_any'][1] == 1))}")

    out = forced if args.only_multi else rows
    if args.limit:
        out = out[:args.limit]
    for r in out:
        a85 = r["r085"]["max_any"]
        a100 = r["r100"]["max_any"]
        o85 = r["r085"]["max_one"]
        s85 = f"{a85[0]}px x{a85[1]}col" if a85 else "none"
        s100 = f"{a100[0]}px x{a100[1]}col" if a100 else "none"
        o = f"{o85[0]}px" if o85 else "none"
        print(json.dumps({
            "work": r["work"], "page": r["page"], "rid": r["rid"], "cells": r["cells"],
            "text": r["text"], "delivered": f"{r['delivered_size']}px x{r['delivered_cols']}col",
            "max@0.85": s85, "max1col@0.85": o, "max@1.00": s100,
            "w85": r["r085"]["w"], "h85": r["r085"]["h"],
            "diag@0.85": a85[3] if a85 else None,
        }, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
