"""生成多页合并 HTML 报告（pages 11-15, 全5阶段）。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from amta.report.assembler import load_from_workspace  # noqa: E402
from amta.report.engine import render_report  # noqa: E402

WORK_ID = "touhou-e2e-orchestrator"
SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
PAGES = list(range(11, 16))
OUT = Path(__file__).resolve().parent / "output" / "e2e-orchestrator-report.html"


def extract_parts(html: str) -> tuple[str, str]:
    """从单页 HTML 提取 <style> 和 <body> 内容。"""
    style_m = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    body_m = re.search(r"<body>(.*?)</body>", html, re.DOTALL)
    style = style_m.group(1) if style_m else ""
    body = body_m.group(1) if body_m else ""
    return style, body


def main() -> None:
    pages_html = []
    css = ""
    summary = []

    for idx in PAGES:
        print(f"Rendering page {idx}...")
        page_report = load_from_workspace(WORK_ID, idx, SRC_DIR)
        result = render_report(page_report)
        style, body = extract_parts(result.html)
        if not css:
            css = style
        pages_html.append(f'<section id="page-{idx}" class="page-section-wrapper">{body}</section>')
        summary.append({
            "page": idx,
            "stages": result.stages_rendered,
            "regions": result.regions_total,
            "aligned": result.regions_aligned,
            "warnings": len(result.warnings),
        })
        print(f"  stages={result.stages_rendered} regions={result.regions_total} "
              f"aligned={result.regions_aligned} warnings={len(result.warnings)}")

    nav = " ".join(
        f'<a href="#page-{s["page"]}" class="nav-link">第{s["page"]}页 '
        f'({s["aligned"]}/{s["regions"]}对齐)</a>'
        for s in summary
    )

    summary_rows = "".join(
        f"<tr><td>第{s['page']}页</td><td>{', '.join(s['stages'])}</td>"
        f"<td>{s['regions']}</td><td>{s['aligned']}</td><td>{s['warnings']}</td></tr>"
        for s in summary
    )

    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Orchestrator 端到端验证报告 — pages 11-15</title>
<style>
{css}
.nav-bar {{ position: sticky; top: 0; background: #1a1a2e; padding: 12px 20px; z-index: 100; display: flex; gap: 16px; flex-wrap: wrap; }}
.nav-link {{ color: #e0e0e0; text-decoration: none; font-size: 14px; padding: 4px 10px; border-radius: 4px; background: #16213e; }}
.nav-link:hover {{ background: #0f3460; }}
.summary-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
.summary-table th, .summary-table td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
.summary-table th {{ background: #f0f0f0; }}
.page-section-wrapper {{ margin-bottom: 40px; border-bottom: 3px solid #eee; padding-bottom: 20px; }}
</style>
</head>
<body>
<div class="nav-bar">
  <strong style="color:#fff;">Orchestrator 端到端验证 (11-15)</strong>
  {nav}
</div>
<div class="container" style="max-width:1400px;margin:0 auto;padding:20px;">
  <h1>Orchestrator 全阶段端到端验证报告</h1>
  <p>工作区: <code>{WORK_ID}</code> | 页面: 11-15 | 阶段: detect → ocr → translate → inpaint → typeset</p>
  <table class="summary-table">
    <thead><tr><th>页面</th><th>渲染阶段</th><th>区域总数</th><th>全阶段对齐</th><th>警告数</th></tr></thead>
    <tbody>{summary_rows}</tbody>
  </table>
  {''.join(pages_html)}
</div>
</body>
</html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(full_html, encoding="utf-8")
    print(f"\nReport written to: {OUT}")
    print(f"Size: {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
