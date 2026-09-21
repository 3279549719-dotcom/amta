"""report ledger 四数对账测试（TDD）。

ledger 是报告页头的一行数字：detect N · ocr M · translate K · rendered L。
只数文本流过手数，不做视觉判断。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image

from amta.report.model import PageReport, StageOutput


def _make_page(tmp_path: Path) -> PageReport:
    """构造假 PageReport：detect 5 框, ocr 5 cells(r05 空text),
    translate 4 cells(r04 空译文), typeset 3 cells(只排了 r01-r03)。"""
    img_path = tmp_path / "test.jpg"
    Image.new("RGB", (100, 100)).save(img_path)

    def _stage(key: str, cells: dict) -> StageOutput:
        return StageOutput(key=key, label=key, cells=cells, render_cell=lambda d: "")

    stages = [
        _stage("detect", {f"r{i:02d}": {"bbox": [0, 0, 10, 10], "confidence": 0.9}
                          for i in range(1, 6)}),
        _stage("ocr", {f"r{i:02d}": {"text": "" if i == 5 else f"text{i}", "bbox": [0, 0, 10, 10]}
                       for i in range(1, 6)}),
        _stage("translate", {f"r{i:02d}": {"translation": "" if i == 4 else f"译文{i}", "bbox": [0, 0, 10, 10]}
                             for i in range(1, 5)}),
        _stage("typeset", {f"r{i:02d}": {"font_size": 12, "bbox": [0, 0, 10, 10]} for i in range(1, 4)}),
    ]
    return PageReport(page_idx=1, raw_image=str(img_path), stages=stages)


def test_compute_ledger_counts(tmp_path):
    """detect 5, ocr 4(r05空text), translate 3(r04空译文), rendered 3。"""
    from amta.report.ledger import compute_ledger

    page = _make_page(tmp_path)
    ledger = compute_ledger(page)

    assert ledger["detect"] == 5
    assert ledger["ocr"] == 4
    assert ledger["translate"] == 3
    assert ledger["rendered"] == 3


def test_compute_ledger_missing_stage_is_none(tmp_path):
    """缺阶段 = None，不算异常（跟 quality_audit 一致）。"""
    from amta.report.ledger import compute_ledger

    img_path = tmp_path / "test.jpg"
    Image.new("RGB", (100, 100)).save(img_path)
    page = PageReport(
        page_idx=1, raw_image=str(img_path),
        stages=[StageOutput(key="detect", label="detect",
                            cells={"r01": {"bbox": []}}, render_cell=lambda d: "")],
    )
    ledger = compute_ledger(page)
    assert ledger["detect"] == 1
    assert ledger["ocr"] is None
    assert ledger["translate"] is None
    assert ledger["rendered"] is None


def test_ledger_rendered_in_page_header(tmp_path):
    """render_page_section 的 HTML 里包含 ledger 行，掉数标红。"""
    from amta.report.engine import render_page_section

    page = _make_page(tmp_path)
    html, _ = render_page_section(page, granularity="region")

    # ledger 行存在
    assert "page-ledger" in html
    assert "detect" in html
    assert "rendered" in html

    # 掉数点标红：5→4→3→3，ocr 和 translate 掉了
    # led-down class 应该出现在 ocr 和 translate 附近
    assert html.count("led-down") == 2

