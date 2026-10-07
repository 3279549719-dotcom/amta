"""对照探针：列数优先会让每个片区掉多少字号、多几列。

读已产出的 canon/typeset（老输出），对每个竖排片区用**当前源码**重算：
- ref  = 参考最大字号（放开列数限制，旧「字号最大优先」会拿到的字号）
- sel  = 列数优先后的字号与列数

输出分布 + 掉幅最大的片区，用于评估「列数最少优先」的真实代价。

用法：
  uv run python scripts/probes/check_column_priority_cost.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from amta.typeset.typeset_engine import (  # noqa: E402
    MIN_SIZE,
    MIN_SIZE_RATIO,
    _vertical_pick,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-id")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--pages", default="")
    ap.add_argument("--dump", default="", help="把全部片区结果写成 JSON 文件")
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

    rows = []
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
                base = int(it.get("src_base_size") or it.get("font_size") or 12)
                min_sz = max(MIN_SIZE, int(base * MIN_SIZE_RATIO))
                try:
                    size, cols, ref, is_one = _vertical_pick(text, fp, bbox, min_sz, base)
                except Exception:
                    continue
                rows.append({
                    "work": work.name, "page": p, "rid": it.get("region_id"),
                    "base": base, "min": min_sz, "ref": ref, "sel": size,
                    "sel_cols": len(cols), "is_one": is_one,
                    "old_size": it.get("font_size"),
                    "old_cols": len(it.get("lines", [])), "cells": len(text),
                })

    n = len(rows)
    changed = [r for r in rows if r["sel_cols"] < r["old_cols"]]
    same = [r for r in rows if r["sel_cols"] == r["old_cols"]]
    more = [r for r in rows if r["sel_cols"] > r["old_cols"]]
    if args.dump:
        Path(args.dump).write_text(
            json.dumps(rows, ensure_ascii=True), encoding="utf-8")
        print("dumped", args.dump, len(rows))
    print(json.dumps({
        "regions": n,
        "columns_reduced": len(changed),
        "columns_same": len(same),
        "columns_increased": len(more),
        "worst_size_drop": max((r["old_size"] - r["sel"] for r in changed), default=0),
        "mean_size_drop": (round(sum(r["old_size"] - r["sel"] for r in changed)
                                 / len(changed), 2) if changed else 0),
    }, ensure_ascii=True))
    for r in sorted(changed, key=lambda r: -(r["old_size"] - r["sel"]))[:25]:
        print(f'  {r["work"]} p{r["page"]} {r["rid"]} base={r["base"]} '
              f'{r["old_size"]}px x{r["old_cols"]}col -> {r["sel"]}px x{r["sel_cols"]}col '
              f'(ref={r["ref"]}, cells={r["cells"]})')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
