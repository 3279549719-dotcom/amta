"""探针：把 HEAD 版引擎与当前引擎在全部已产出竖排片区上逐个对比。

- OLD = `git show HEAD:src/amta/typeset/typeset_engine.py`（最近一次提交的产线行为）
- NEW = 当前工作区源码（列数少优先，受相对下限约束）

用同一份 bbox / 冻结译文 / 字体，分别算 (字号, 方向, 分列)。OLD 通过
importlib 以独立模块名加载，避免污染 sys.modules 里的 amta 包。

用法：
  uv run python scripts/probes/compare_old_new_engine.py --all --dump artifacts/old_new_rows.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

OLD_PATH = REPO / "artifacts" / "_oldengine" / "typeset_engine_old.py"


def load_old():
    spec = importlib.util.spec_from_file_location("typeset_engine_old", OLD_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["typeset_engine_old"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-id")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--pages", default="")
    ap.add_argument("--dump", default="")
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    old = load_old()
    from amta.typeset import typeset_engine as new

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
                base = it.get("src_base_size") or it.get("font_size") or 12
                try:
                    o_size, o_dir, o_lines = old.fit_font_size(
                        text, fp, bbox, preferred_direction="vertical",
                        base_size=int(base))
                    n_size, n_dir, n_lines = new.fit_font_size(
                        text, fp, bbox, preferred_direction="vertical",
                        base_size=int(base))
                except Exception:
                    continue
                rows.append({
                    "work": work.name, "page": p, "rid": it.get("region_id"),
                    "base": int(base), "cells": len(text),
                    "old_size": o_size, "old_cols": len(o_lines),
                    "new_size": n_size, "new_cols": len(n_lines),
                })

    if args.dump:
        Path(args.dump).write_text(json.dumps(rows, ensure_ascii=True), encoding="utf-8")
        print("dumped", args.dump, len(rows))

    changed = [r for r in rows
               if (r["new_cols"], -r["new_size"]) != (r["old_cols"], -r["old_size"])]
    fewer = [r for r in changed if r["new_cols"] < r["old_cols"]]
    more = [r for r in changed if r["new_cols"] > r["old_cols"]]
    print(json.dumps({
        "regions": len(rows),
        "identical": len(rows) - len(changed),
        "changed": len(changed),
        "fewer_cols": len(fewer),
        "more_cols": len(more),
        "fewer_cols_mean_size_delta": (
            round(sum(r["new_size"] - r["old_size"] for r in fewer) / len(fewer), 2)
            if fewer else 0),
        "fewer_cols_worst_size_delta": (
            min((r["new_size"] - r["old_size"] for r in fewer), default=0)),
        "more_cols_improved_size": sum(1 for r in more if r["new_size"] >= r["old_size"]),
    }, ensure_ascii=True))
    print("-- fewer columns (sample) --")
    for r in sorted(fewer, key=lambda r: r["new_size"] - r["old_size"])[:args.show]:
        print("  %s p%s %s base=%s cells=%d  %spx x%dcol -> %spx x%dcol" % (
            r["work"], r["page"], r["rid"], r["base"], r["cells"],
            r["old_size"], r["old_cols"], r["new_size"], r["new_cols"]))
    print("-- more columns (sample) --")
    for r in more[:args.show]:
        print("  %s p%s %s base=%s cells=%d  %spx x%dcol -> %spx x%dcol" % (
            r["work"], r["page"], r["rid"], r["base"], r["cells"],
            r["old_size"], r["old_cols"], r["new_size"], r["new_cols"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
