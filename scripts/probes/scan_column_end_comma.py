"""扫描全部页面的竖排列末冗余逗号（Task 5）。

只读 typeset 产物（不上屏、不重渲染），统计每个页面有多少竖排列以逗号族
标点结尾——这就是修复前会"悬在列底"的冗余标点。

用法：
  uv run python scripts/probes/scan_column_end_comma.py
  uv run python scripts/probes/scan_column_end_comma.py --top 10
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from amta.common.encoding import force_utf8_stdio  # noqa: E402

force_utf8_stdio()  # Windows stdout 默认 cp936，中文输出必须走 UTF-8 收口点

SRC_ROOT = Path(r"E:\manga translator agent\workspace\touhou-getten-shinchi")
COMMA_FAMILY = set("，、,")


def _page_num(path: Path) -> int:
    return int(path.stem.split("_")[-1])


def scan(src_root: Path) -> list[dict]:
    typeset_dir = src_root / "artifacts" / "typeset"
    if not typeset_dir.exists():
        raise SystemExit(f"typeset 产物目录不存在: {typeset_dir}")

    per_page = []
    for f in sorted(typeset_dir.glob("page_*.json"), key=_page_num):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        page = str(doc.get("page") or f.stem).removeprefix("page_")
        hits = []
        n_vertical = 0
        for item in doc.get("rendered_items", []):
            if item.get("layout_direction") != "vertical":
                continue
            n_vertical += 1
            rid = item.get("region_id", "?")
            for ci, col in enumerate(item.get("lines", [])):
                if col and col[-1] in COMMA_FAMILY:
                    hits.append({"region_id": rid, "line_idx": ci,
                                 "column_text": col, "is_final_column":
                                     ci == len(item["lines"]) - 1})
        per_page.append({"page": page, "n_vertical_regions": n_vertical,
                         "n_hits": len(hits), "hits": hits})
    return per_page


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-root", type=Path, default=SRC_ROOT)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--out", type=Path,
                    default=Path("workspace/column-end-comma-fix/scan.json"))
    args = ap.parse_args()

    per_page = scan(args.src_root)
    total = sum(p["n_hits"] for p in per_page)
    pages_with = [p for p in per_page if p["n_hits"]]

    print(f"扫描 {len(per_page)} 页，其中 {len(pages_with)} 页存在竖排列末冗余逗号")
    print(f"合计 {total} 处\n")

    # 逗号落在"末列"还是"非末列"
    final_col = sum(1 for p in per_page for h in p["hits"] if h["is_final_column"])
    print(f"  非末列列末逗号: {total - final_col} 处")
    print(f"  末列列末逗号  : {final_col} 处\n")

    chars = Counter(h["column_text"][-1] for p in per_page for h in p["hits"])
    print(f"  标点分布: {dict(chars)}\n")

    print(f"问题最多的 {args.top} 页:")
    for p in sorted(pages_with, key=lambda p: -p["n_hits"])[:args.top]:
        rids = sorted({h["region_id"] for h in p["hits"]})
        print(f"  page_{p['page']:>3}: {p['n_hits']:>2} 处  {rids}")

    print("\n逐页明细（仅列有问题的页）:")
    for p in pages_with:
        print(f"  page_{p['page']}: "
              f"{[(h['region_id'], h['column_text']) for h in p['hits']]}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(
            {"n_pages_scanned": len(per_page), "n_pages_affected": len(pages_with),
             "n_hits_total": total, "n_hits_non_final_column": total - final_col,
             "punctuation_counts": dict(chars), "per_page": per_page},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n明细已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
