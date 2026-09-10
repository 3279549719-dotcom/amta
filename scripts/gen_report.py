"""gen_report — amta HTML 报告统一入口（深接口 amta.report 的薄壳 CLI）。

用法:
  # 通用管线报告（默认）
  python scripts/gen_report.py --work-id <id> --src-dir <原图目录> --pages 1-5 --out report.html

  # 其他报告类型
  python scripts/gen_report.py --type final --work-id <id> --src-dir <dir> --pages 1-5 --out report.html
  python scripts/gen_report.py --type stage4 --src-dir <dir> --result-dir <dir> --pages 11-20 --out report.html
  python scripts/gen_report.py --type inpaint_ab --exp-dir <dir> --src-dir <dir> --pages 11-15 --out report.html
  python scripts/gen_report.py --type ab --plan-a-dir <dir> --plan-b-dir <dir> --out report.html
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.common.paths import ROOT as _PATHS_ROOT
from amta.report import (
    load_from_workspace,
    render_ab_report,
    render_final_report,
    render_inpaint_ab_report,
    render_report,
    render_stage4_report,
)
from amta.report.pipeline_report import render_pipeline_report

ROOT = _PATHS_ROOT  # 统一用 paths.ROOT，不自己算


def parse_pages(spec: str) -> list[int]:
    """解析 --pages 参数，支持 '1-5' 或 '1,3,5' 或混合。"""
    pages = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            pages.extend(range(int(lo), int(hi) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def _cmd_pipeline(a: argparse.Namespace) -> int:
    if not a.work_id or not a.src_dir or not a.pages or not a.out:
        print("[gen_report] pipeline 类型需要 --work-id --src-dir --pages --out")
        return 1

    page_nums = parse_pages(a.pages)
    page_sections = []
    total_warnings = 0
    total_aligned = 0
    total_regions = 0

    for n in page_nums:
        try:
            page = load_from_workspace(
                work_id=a.work_id,
                page_idx=n,
                src_dir=a.src_dir,
                workspace_root=a.workspace_root,
            )
        except (FileNotFoundError, ValueError) as e:
            print(f"[gen_report] page {n} 跳过: {e}")
            continue

        result = render_report(page)
        inner = result.html.split('<div class="page-section">', 1)[-1]
        inner = inner.rsplit('</div>\n  <div class="footer">', 1)[0]
        page_sections.append(f'<div class="page-section">{inner}')

        total_warnings += len(result.warnings)
        total_aligned += result.regions_aligned
        total_regions += result.regions_total
        print(f"[gen_report] page_{n}: stages={result.stages_rendered} "
              f"regions={result.regions_total} aligned={result.regions_aligned} "
              f"warnings={len(result.warnings)} ({result.render_time_ms:.0f}ms)")

    if not page_sections:
        print("[gen_report] 没有成功渲染任何页面")
        return 1

    out = render_pipeline_report(
        page_sections,
        work_id=a.work_id,
        pages=a.pages,
        out_path=a.out,
        regions_total=total_regions,
        regions_aligned=total_aligned,
        warnings=total_warnings,
    )
    print(f"[gen_report] 报告 -> {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


def _cmd_final(a: argparse.Namespace) -> int:
    if not a.work_id or not a.src_dir or not a.pages:
        print("[gen_report] final 类型需要 --work-id --src-dir --pages")
        return 1
    pages = parse_pages(a.pages)
    out = a.out or ROOT / "output" / f"{a.work_id}-final-report.html"
    html = render_final_report(a.work_id, a.src_dir, pages, artifacts_dir=a.workspace_root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"[gen_report] 报告 -> {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


def _cmd_stage4(a: argparse.Namespace) -> int:
    if not a.src_dir or not a.result_dir:
        print("[gen_report] stage4 类型需要 --src-dir --result-dir")
        return 1
    pages = parse_pages(a.pages or "11-20")
    out = a.out or ROOT / "output" / "stage4-report.html"
    render_stage4_report(a.src_dir, a.result_dir, pages, out_path=out)
    return 0


def _cmd_inpaint_ab(a: argparse.Namespace) -> int:
    if not a.exp_dir or not a.src_dir:
        print("[gen_report] inpaint_ab 类型需要 --exp-dir --src-dir")
        return 1
    pages = parse_pages(a.pages or "11-15")
    out = a.out or Path(a.exp_dir) / "inpaint_speed_ab_report.html"
    render_inpaint_ab_report(a.exp_dir, a.src_dir, pages=pages, out_path=out)
    return 0


def _cmd_ab(a: argparse.Namespace) -> int:
    if not a.plan_a_dir or not a.plan_b_dir:
        print("[gen_report] ab 类型需要 --plan-a-dir --plan-b-dir")
        return 1
    out = a.out or ROOT / "output" / "stage4-ab-comparison-report.html"
    render_ab_report(a.plan_a_dir, a.plan_b_dir, out_path=out)
    return 0


_DISPATCH = {
    "pipeline": _cmd_pipeline,
    "final": _cmd_final,
    "stage4": _cmd_stage4,
    "inpaint_ab": _cmd_inpaint_ab,
    "ab": _cmd_ab,
}


def main() -> int:
    ap = argparse.ArgumentParser(description="amta HTML 报告统一入口")
    ap.add_argument("--type", choices=list(_DISPATCH.keys()), default="pipeline",
                    help="报告类型（默认 pipeline）")
    ap.add_argument("--work-id", default=None, help="workspace 工作区 ID")
    ap.add_argument("--src-dir", type=Path, default=None, help="源图目录 (N.jpg)")
    ap.add_argument("--pages", default=None, help="页码范围，如 1-5 或 1,3,5")
    ap.add_argument("--out", type=Path, default=None, help="输出 HTML 路径")
    ap.add_argument("--workspace-root", type=Path, default=None, help="workspace 根目录")
    ap.add_argument("--result-dir", type=Path, default=None, help="stage4 结果目录")
    ap.add_argument("--exp-dir", type=Path, default=None, help="inpaint A/B 实验目录")
    ap.add_argument("--plan-a-dir", type=Path, default=None, help="A/B 方案A 目录")
    ap.add_argument("--plan-b-dir", type=Path, default=None, help="A/B 方案B 目录")
    a = ap.parse_args()

    return _DISPATCH[a.type](a)


if __name__ == "__main__":
    raise SystemExit(main())
