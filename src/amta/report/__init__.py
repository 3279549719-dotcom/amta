"""amta.report — 深接口 HTML 报告工具（ADR-024）。

唯一公共入口: render_report(page: PageReport) -> ReportResult
数据模型: PageReport, StageOutput, ReportResult
数据组装: load_page_report, load_from_workspace
CLI: scripts/gen_report.py
"""
from .assembler import load_from_workspace, load_page_report
from .engine import (
    render_compare_section,
    render_image_panel,
    render_page_section,
    render_region_table,
    render_report,
    render_report_shell,
)
from .model import PageReport, ReportResult, StageOutput

__all__ = [
    "PageReport",
    "ReportResult",
    "StageOutput",
    "load_from_workspace",
    "load_page_report",
    "render_compare_section",
    "render_image_panel",
    "render_page_section",
    "render_region_table",
    "render_report",
    "render_report_shell",
]
