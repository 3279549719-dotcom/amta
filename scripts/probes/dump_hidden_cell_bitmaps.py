"""把"被隐藏的字形格"导成 ASCII 位图 —— 无图像输入时的视觉证据（Task 4/5）。

本会话的模型没有图像输入能力，无法直接看 PNG。这个脚本把 render_report.json
里每个被隐藏字格的 before/after 像素导成文本位图，让"逗号字形确实被移除、
且该格其他内容/位置不变"这件事可以被逐像素核对，而不是只靠一句像素计数。

用法：
  uv run python scripts/probes/dump_hidden_cell_bitmaps.py --out cell_bitmaps.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PIL import Image  # noqa: E402

OUT_ROOT = Path("workspace/column-end-comma-fix")
DARK = 128
LIGHT = 240


def _rows(img: Image.Image, cell, step: int = 2, xstep: int = 1) -> list[str]:
    x1, y1, x2, y2 = (int(v) for v in cell)
    px = img.load()
    out = []
    for y in range(max(0, y1), min(img.height, y2), step):
        out.append("".join(
            "#" if sum(px[x, y]) / 3 < DARK
            else "." if sum(px[x, y]) / 3 < LIGHT else " "
            for x in range(max(0, x1), min(img.width, x2), xstep)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", type=Path, default=OUT_ROOT)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    out_path = args.out or (args.out_root / "cell_bitmaps.txt")

    reports = json.loads((args.out_root / "render_report.json").read_text(encoding="utf-8"))
    lines: list[str] = []
    total = 0
    ok = 0

    for rep in reports:
        page = rep["page"]
        before = Image.open(args.out_root / "before" / f"page_{page}_final.png").convert("RGB")
        after = Image.open(args.out_root / "after" / f"page_{page}_final.png").convert("RGB")
        lines.append("#" * 74)
        lines.append(f"# page_{page}  列末逗号 {rep['n_column_end_commas']} 处  "
                     f"全图改动 {rep['total_changed_pixels']}px  "
                     f"lines 元数据一致={rep['lines_metadata_identical']}")
        lines.append("#" * 74)
        for c in rep["checks"]:
            total += 1
            good = c["ink_before"] > 0 and c["ink_after"] == 0
            ok += good
            lines.append("")
            lines.append(f"## {c['region_id']} 列{c['line_idx']} 字格{c['char_idx']} "
                         f"{c['column_text']!r}  cell={c['cell']}")
            lines.append(f"   ink before={c['ink_before']} after={c['ink_after']}  "
                         f"{'OK 字形已移除' if good else '!! 异常'}")
            rb = _rows(before, c["cell"])
            ra = _rows(after, c["cell"])
            width = max(len(r) for r in rb)
            lines.append("   " + "BEFORE".ljust(width) + " | AFTER")
            for a, b in zip(rb, ra):
                lines.append("   " + a.ljust(width) + " | " + b)
        lines.append("")

    lines.append(f"合计 {total} 处列末逗号，{ok} 处 before 有墨 / after 无墨。")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"已写入 {out_path}  ({out_path.stat().st_size // 1024} KB)")
    print(f"合计 {total} 处列末逗号，{ok} 处验证通过（before 有墨 → after 无墨）")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
