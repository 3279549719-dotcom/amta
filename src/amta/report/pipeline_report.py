"""pipeline_report — 通用管线报告的文档外壳（深接口模块）。

`scripts/gen_report.py --type pipeline`（默认）是本模块的薄壳 CLI。

2026-09-10 迁入：原先这套 HTML 外壳写在 `scripts/gen_report.py` 里（85–122 行），
违反 CLAUDE.md「HTML 报告铁律」。当时的 footer 还写着"深接口渲染引擎"，
外壳本身却住在 scripts/ —— 由 `tests/test_typeset_review.py::TestHtmlReportIronLaw`
机械守住（不靠自觉）。

职责边界：本模块只负责**把已经渲染好的 page_sections 装进文档外壳**；
页面内部（图片 + 区域表）由 `amta.report.engine` 的渲染结果提供。
"""
from __future__ import annotations

from pathlib import Path

_STYLE = """
body { font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; background:#f0f2f5; color:#1a1a2e; margin:0; padding:24px; line-height:1.6; }
.container { max-width:1400px; margin:0 auto; }
h1 { font-size:22px; margin-bottom:4px; }
.subtitle { color:#666; font-size:13px; margin-bottom:20px; }
.stats { display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }
.stat { background:#fff; border-radius:10px; padding:12px 18px; box-shadow:0 1px 4px rgba(0,0,0,.06); min-width:100px; }
.stat .num { font-size:24px; font-weight:700; color:#1e40af; }
.stat .lbl { font-size:11px; color:#666; }
.page-section { background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,.06); }
.page-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding-bottom:8px; border-bottom:2px solid #f0f0f0; }
.page-title { font-size:16px; font-weight:700; color:#1e40af; }
.layout { display:flex; gap:20px; align-items:flex-start; }
.img-panel { flex:0 0 45%; }
.img-panel img { width:100%; border-radius:8px; border:1px solid #e5e7eb; }
.table-panel { flex:1; overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:12px; }
th { background:#f3f4f6; padding:6px 8px; text-align:left; border-bottom:2px solid #e5e7eb; }
td { padding:6px 8px; border-bottom:1px solid #f3f4f6; vertical-align:top; }
tr:hover { background:#f9fafb; }
.rid { font-weight:600; color:#1e40af; white-space:nowrap; }
.footer { text-align:center; color:#999; font-size:11px; margin-top:24px; padding:16px; }
"""

_DOC_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>amta 管线报告 — {work_id}</title>
<style>{style}</style>
</head>
<body>
<div class="container">
  <h1>amta 管线报告 — {work_id}</h1>
  <div class="subtitle">页面: {pages} ｜ 总区域: {regions_total} ｜ 对齐: {regions_aligned} ｜ 警告: {warnings}</div>
  {sections}
  <div class="footer">amta report tool — 深接口渲染引擎</div>
</div>
</body>
</html>"""


def render_pipeline_report(
    page_sections: list[str],
    *,
    work_id: str,
    pages: str,
    out_path: Path,
    regions_total: int = 0,
    regions_aligned: int = 0,
    warnings: int = 0,
) -> Path:
    """把已渲染的每页片段装进通用管线报告外壳并写盘。

    Args:
        page_sections: 每页的 HTML 片段（由 engine 渲染，顺序即页面顺序）。
        work_id: 工作区 id（进标题与副标题）。
        pages: 页码范围说明（进副标题）。
        out_path: 输出 HTML 路径（父目录自动创建）。
        regions_total / regions_aligned / warnings: 汇总统计。

    Returns:
        Path: 实际写出的 HTML 路径。
    """
    html = _DOC_TEMPLATE.format(
        work_id=work_id,
        style=_STYLE,
        pages=pages,
        regions_total=regions_total,
        regions_aligned=regions_aligned,
        warnings=warnings,
        sections="".join(page_sections),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
