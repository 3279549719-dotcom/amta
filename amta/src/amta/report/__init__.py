"""amta.report — 深接口 HTML 报告工具。

唯一公共入口: render_report(page: PageReport) -> ReportResult
数据模型: PageReport, StageOutput, ReportResult
数据组装: load_page_report, load_from_workspace
"""
from .model import PageReport, ReportResult, StageOutput
from .engine import render_report
from .assembler import load_page_report, load_from_workspace

__all__ = [
    "render_report",
    "PageReport",
    "StageOutput",
    "ReportResult",
    "load_page_report",
    "load_from_workspace",
]
