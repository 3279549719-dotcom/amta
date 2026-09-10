"""gen_ab_report — Stage4 框外字去除 A/B 对比报告 CLI（amta.report.ab_report 的薄壳）。

用法:
  python scripts/gen_ab_report.py [--plan-a-dir DIR] [--plan-b-dir DIR] [--out output.html]

无参数时使用实验默认路径。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.report.ab_report import render_ab_report

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PLAN_A = ROOT / "output" / "tmp" / "refine_mask_batch_11_20"
DEFAULT_PLAN_B = ROOT / "output" / "tmp" / "sam_mask_probe"
DEFAULT_OUT = ROOT / "output" / "stage4-ab-comparison-report.html"


def main() -> int:
    ap = argparse.ArgumentParser(description="Stage4 框外字去除 A/B 对比报告")
    ap.add_argument("--plan-a-dir", type=Path, default=DEFAULT_PLAN_A, help="方案A结果目录")
    ap.add_argument("--plan-b-dir", type=Path, default=DEFAULT_PLAN_B, help="方案B结果目录")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出 HTML 路径")
    a = ap.parse_args()

    render_ab_report(a.plan_a_dir, a.plan_b_dir, out_path=a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
