"""gen_stage4_report — Stage4 验证报告 CLI（amta.report.stage4_report 的薄壳）。

用法:
  python scripts/gen_stage4_report.py [--src-dir DIR] [--result-dir DIR] \
      [--pages 11-20] [--out output.html]

无参数时使用 Stage4 实验默认路径（兼容 run.ps1 report 命令）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.report.stage4_report import render_stage4_report

DEFAULT_SRC = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
DEFAULT_RESULT = Path(__file__).resolve().parent.parent / "output" / "tmp" / "stage4_e2e_11_20"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "output" / "stage4-e2e-11-20-report.html"
DEFAULT_PAGES = "11-20"


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
    ap = argparse.ArgumentParser(description="Stage4 验证报告（mask+inpaint 逐页对比）")
    ap.add_argument("--src-dir", type=Path, default=DEFAULT_SRC, help="原图目录")
    ap.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT,
                    help="stage4 结果目录（含 page_N_inpaint.json + clean/）")
    ap.add_argument("--pages", default=DEFAULT_PAGES, help="页码范围，如 11-20 或 11,13,15")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出 HTML 路径")
    a = ap.parse_args()

    pages = parse_pages(a.pages)
    render_stage4_report(a.src_dir, a.result_dir, pages, out_path=a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
