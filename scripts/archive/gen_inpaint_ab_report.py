"""gen_inpaint_ab_report — Inpainting 速度 A/B 对比报告 CLI（amta.report.inpaint_ab_report 的薄壳）。

用法:
  python scripts/gen_inpaint_ab_report.py [--exp-dir DIR] [--src-dir DIR] \
      [--pages 11-15] [--out output.html]

无参数时使用实验默认路径。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.report.inpaint_ab_report import render_inpaint_ab_report

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXP = ROOT / "output" / "tmp" / "inpaint_speed_exp"
DEFAULT_SRC = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
DEFAULT_OUT = DEFAULT_EXP / "inpaint_speed_ab_report.html"
DEFAULT_PAGES = "11-15"


def parse_pages(spec: str) -> list[int]:
    pages = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            pages.extend(range(int(lo), int(hi) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def main() -> int:
    ap = argparse.ArgumentParser(description="Inpainting 速度 A/B 对比报告")
    ap.add_argument("--exp-dir", type=Path, default=DEFAULT_EXP, help="实验结果目录")
    ap.add_argument("--src-dir", type=Path, default=DEFAULT_SRC, help="原图目录")
    ap.add_argument("--pages", default=DEFAULT_PAGES, help="页码范围，如 11-15 或 11,13,15")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出 HTML 路径")
    a = ap.parse_args()

    pages = parse_pages(a.pages)
    render_inpaint_ab_report(a.exp_dir, a.src_dir, pages=pages, out_path=a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
