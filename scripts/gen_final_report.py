"""gen_final_report — 三阶段流水线最终报告 CLI（amta.report.final_report 的薄壳）。

用法: python scripts/gen_final_report.py --work-id <id> --src-dir <原图目录> --out <output.html>

深接口: amta.report.final_report.render_final_report()
新报告需求优先用 gen_report.py（amta.report 通用渲染引擎）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.report.final_report import render_final_report


def main() -> int:
    ap = argparse.ArgumentParser(description="生成三阶段流水线最终 HTML 报告")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--src-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--pages", type=int, nargs="+", default=[0, 1, 2], help="page indices (0-based)")
    a = ap.parse_args()

    html = render_final_report(a.work_id, a.src_dir, a.pages)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(html, encoding="utf-8")
    print(f"Report generated: {a.out} ({a.out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
