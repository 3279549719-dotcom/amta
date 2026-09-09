"""报告收敛测试 — 验证 amta.report 各报告模块的公共接口。

TDD 接缝：每个报告模块的 render_*() 函数是公共接口，
测试通过构造 fake artifacts 断言 HTML 输出，不碰真实数据。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------- fixtures ----------

def _make_page_artifacts(art_dir: Path, page_idx: int,
                         ocr_text: str = "hello",
                         trans_text: str = "你好",
                         ) -> None:
    """在 art_dir 下构造一页的 detection/canon/translation 三个 JSON。"""
    page = f"page_{page_idx}"
    (art_dir / f"{page}_detection.json").write_text(json.dumps({
        "n_boxes": 2,
        "source_engines": ["rtdetr-v2"],
        "conf_threshold": 0.7,
    }), encoding="utf-8")
    (art_dir / f"{page}_canon.json").write_text(json.dumps({
        "items": [{
            "region_id": f"r{page_idx}",
            "text": ocr_text,
            "bbox": [10, 10, 100, 50],
            "confidence": 0.9,
        }],
        "n_regions": 1,
    }), encoding="utf-8")
    (art_dir / f"{page}_translation.json").write_text(json.dumps({
        "translations": {f"r{page_idx}": trans_text},
    }), encoding="utf-8")


def _make_raw_image(src_dir: Path, page_idx: int) -> None:
    src_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 100), "white").save(src_dir / f"{page_idx}.jpg")


@pytest.fixture
def fake_workspace(tmp_path):
    """构造一个含 2 页 fake artifacts 的 workspace。"""
    art_dir = tmp_path / "workspace" / "test-work" / "artifacts"
    art_dir.mkdir(parents=True)
    src_dir = tmp_path / "src"
    for idx in (0, 1):
        _make_page_artifacts(art_dir, idx, ocr_text=f"ocr{idx}", trans_text=f"译{idx}")
        _make_raw_image(src_dir, idx)
    return {"art_dir": art_dir, "src_dir": src_dir, "work_id": "test-work"}


# ---------- final_report ----------

class TestFinalReport:
    """amta.report.final_report.render_final_report 行为测试。"""

    def test_returns_html_string(self, fake_workspace):
        from amta.report.final_report import render_final_report
        html = render_final_report(
            fake_workspace["work_id"],
            fake_workspace["src_dir"],
            [0],
            artifacts_dir=fake_workspace["art_dir"],
        )
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_contains_page_data(self, fake_workspace):
        from amta.report.final_report import render_final_report
        html = render_final_report(
            fake_workspace["work_id"],
            fake_workspace["src_dir"],
            [0],
            artifacts_dir=fake_workspace["art_dir"],
        )
        # 页号
        assert "Page 0" in html
        # OCR 原文
        assert "ocr0" in html
        # 译文
        assert "译0" in html
        # bubble type badge
        assert "OCR 原文" in html

    def test_summary_table_has_counts(self, fake_workspace):
        from amta.report.final_report import render_final_report
        html = render_final_report(
            fake_workspace["work_id"],
            fake_workspace["src_dir"],
            [0, 1],
            artifacts_dir=fake_workspace["art_dir"],
        )
        # 合计行
        assert "合计" in html
        assert "2 页" in html
        # 每页检测框数
        assert "2 boxes" in html

    def test_missing_artifacts_dir_raises(self, tmp_path):
        from amta.report.final_report import render_final_report
        src = tmp_path / "src"
        src.mkdir()
        with pytest.raises(FileNotFoundError):
            render_final_report("nonexistent", src, [0], artifacts_dir=tmp_path / "nope")

    def test_skip_page_with_missing_artifacts(self, fake_workspace):
        """缺 artifacts 的页被跳过，不崩溃，其余页正常渲染。"""
        from amta.report.final_report import render_final_report
        # page 99 没有 artifacts
        html = render_final_report(
            fake_workspace["work_id"],
            fake_workspace["src_dir"],
            [0, 99],
            artifacts_dir=fake_workspace["art_dir"],
        )
        assert "Page 0" in html
        assert "Page 99" not in html

    def test_exported_from_package(self):
        """render_final_report 应从 amta.report 顶层可导入。"""
        from amta.report import render_final_report
        assert callable(render_final_report)


# ---------- stage4_report ----------

def _make_stage4_data(result_dir: Path, page_idx: int,
                      has_free: bool = True) -> None:
    """构造 stage4 报告所需的 inpaint.json + clean 图。"""
    result_dir.mkdir(parents=True, exist_ok=True)
    clean_dir = result_dir / "clean"
    clean_dir.mkdir(exist_ok=True)

    actions = []
    if has_free:
        actions.append({
            "action": "inpaint",
            "region_id": f"free{page_idx}",
            "bbox": [10, 20, 100, 80],
        })
        actions.append({
            "action": "fill_white",
            "region_id": f"bubble{page_idx}",
            "bbox": [200, 200, 300, 240],
        })
    (result_dir / f"page_{page_idx}_inpaint.json").write_text(
        json.dumps({"actions": actions}, ensure_ascii=False), encoding="utf-8")
    Image.new("RGB", (200, 200), "white").save(clean_dir / f"page_{page_idx}_clean.png")


class TestStage4Report:
    """amta.report.stage4_report 行为测试。"""

    def test_extract_text_free_boxes(self):
        from amta.report.stage4_report import extract_text_free_boxes
        inpaint_json = {
            "actions": [
                {"action": "inpaint", "region_id": "r0", "bbox": [1, 2, 3, 4]},
                {"action": "fill_white", "region_id": "r1", "bbox": [5, 6, 7, 8]},
                {"action": "inpaint", "region_id": "r2", "bbox": [9, 10, 11, 12]},
            ],
        }
        boxes = extract_text_free_boxes(inpaint_json)
        assert set(boxes.keys()) == {"r0", "r2"}
        assert boxes["r0"] == [1, 2, 3, 4]

    def test_extract_no_free_boxes(self):
        from amta.report.stage4_report import extract_text_free_boxes
        assert extract_text_free_boxes({"actions": []}) == {}
        assert extract_text_free_boxes({}) == {}

    def test_render_with_free_boxes(self, tmp_path, monkeypatch):
        from amta.report import stage4_report
        # mock refine_text_mask 避免依赖 opencv 真实运算
        monkeypatch.setattr(stage4_report, "refine_text_mask",
                            lambda img, bboxes, pad=4: __import__("numpy").zeros((200, 200), dtype="uint8"))
        src = tmp_path / "src"
        src.mkdir()
        Image.new("RGB", (200, 200), "white").save(src / "11.jpg")
        result = tmp_path / "result"
        _make_stage4_data(result, 11, has_free=True)

        html = stage4_report.render_stage4_report(src, result, [11])
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html
        assert "第 11 页" in html
        assert "free11" in html
        assert "inpaint 框" in html

    def test_render_no_free_boxes(self, tmp_path, monkeypatch):
        from amta.report import stage4_report
        monkeypatch.setattr(stage4_report, "refine_text_mask",
                            lambda img, bboxes, pad=4: __import__("numpy").zeros((200, 200), dtype="uint8"))
        src = tmp_path / "src"
        src.mkdir()
        Image.new("RGB", (200, 200), "white").save(src / "12.jpg")
        result = tmp_path / "result"
        _make_stage4_data(result, 12, has_free=False)

        html = stage4_report.render_stage4_report(src, result, [12])
        assert "无 inpaint 框" in html

    def test_render_skip_missing_raw(self, tmp_path, monkeypatch):
        from amta.report import stage4_report
        monkeypatch.setattr(stage4_report, "refine_text_mask",
                            lambda img, bboxes, pad=4: __import__("numpy").zeros((200, 200), dtype="uint8"))
        src = tmp_path / "src"
        src.mkdir()
        # 11.jpg 不存在，12.jpg 存在
        Image.new("RGB", (200, 200), "white").save(src / "12.jpg")
        result = tmp_path / "result"
        _make_stage4_data(result, 11, has_free=True)
        _make_stage4_data(result, 12, has_free=True)

        html = stage4_report.render_stage4_report(src, result, [11, 12])
        assert "第 12 页" in html
        assert "第 11 页" not in html

    def test_render_writes_out_file(self, tmp_path, monkeypatch):
        from amta.report import stage4_report
        monkeypatch.setattr(stage4_report, "refine_text_mask",
                            lambda img, bboxes, pad=4: __import__("numpy").zeros((200, 200), dtype="uint8"))
        src = tmp_path / "src"
        src.mkdir()
        Image.new("RGB", (200, 200), "white").save(src / "11.jpg")
        result = tmp_path / "result"
        _make_stage4_data(result, 11, has_free=True)
        out = tmp_path / "out.html"

        html = stage4_report.render_stage4_report(src, result, [11], out_path=out)
        assert out.exists()
        assert out.read_text(encoding="utf-8") == html


# ---------- ab_report (框外字 A/B 对比) ----------

def _make_ab_summaries(plan_a_dir: Path, plan_b_dir: Path) -> None:
    """构造 A/B 实验的 summary.json。"""
    plan_a_dir.mkdir(parents=True, exist_ok=True)
    plan_b_dir.mkdir(parents=True, exist_ok=True)
    plan_a = {"page_11": {"free_boxes": 1, "rect_pixels": 1000}}
    plan_b = {
        "page_11": {
            "free_boxes": 1, "rect_pixels": 1000,
            "plan_a_pixels": 200, "plan_b_pixels": 700,
            "plan_a_reduction_pct": 80.0, "plan_b_reduction_pct": 30.0,
            "ab_iou": 0.15, "plan_a_time": 0.05, "plan_b_time": 25.0,
        },
    }
    (plan_a_dir / "summary.json").write_text(
        json.dumps(plan_a, ensure_ascii=False), encoding="utf-8")
    (plan_b_dir / "summary.json").write_text(
        json.dumps(plan_b, ensure_ascii=False), encoding="utf-8")


class TestAbReport:
    """amta.report.ab_report 行为测试。"""

    def test_render_returns_html(self, tmp_path):
        from amta.report.ab_report import render_ab_report
        plan_a = tmp_path / "plan_a"
        plan_b = tmp_path / "plan_b"
        _make_ab_summaries(plan_a, plan_b)
        html = render_ab_report(plan_a, plan_b)
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html
        assert "A/B 对比" in html

    def test_render_contains_metrics(self, tmp_path):
        from amta.report.ab_report import render_ab_report
        plan_a = tmp_path / "plan_a"
        plan_b = tmp_path / "plan_b"
        _make_ab_summaries(plan_a, plan_b)
        html = render_ab_report(plan_a, plan_b)
        assert "80.0%" in html  # plan A reduction
        assert "30.0%" in html  # plan B reduction
        assert "page_11" in html

    def test_render_writes_out(self, tmp_path):
        from amta.report.ab_report import render_ab_report
        plan_a = tmp_path / "plan_a"
        plan_b = tmp_path / "plan_b"
        _make_ab_summaries(plan_a, plan_b)
        out = tmp_path / "ab.html"
        html = render_ab_report(plan_a, plan_b, out_path=out)
        assert out.exists()
        assert out.read_text(encoding="utf-8") == html


# ---------- inpaint_ab_report (inpaint 速度 A/B) ----------

def _make_inpaint_summaries(exp_dir: Path) -> None:
    """构造 inpaint 速度实验的 summary_*.json。"""
    exp_dir.mkdir(parents=True, exist_ok=True)
    for mode in ["baseline", "p0", "p1_cpu", "p1_manga"]:
        data = [{"page": 11, "avg": 100.0, "n_free": 2}]
        (exp_dir / f"summary_{mode}.json").write_text(
            json.dumps(data), encoding="utf-8")


class TestInpaintAbReport:
    """amta.report.inpaint_ab_report 行为测试。"""

    def test_load_summary(self, tmp_path):
        from amta.report.inpaint_ab_report import load_summary
        exp = tmp_path / "exp"
        exp.mkdir()
        (exp / "summary_baseline.json").write_text(
            json.dumps([{"page": 11, "avg": 100.0, "n_free": 2},
                        {"page": 12, "error": "failed"}]),
            encoding="utf-8")
        result = load_summary(exp, "baseline")
        assert 11 in result
        assert result[11]["avg"] == 100.0
        assert 12 not in result  # error entries filtered

    def test_load_summary_missing_file(self, tmp_path):
        from amta.report.inpaint_ab_report import load_summary
        assert load_summary(tmp_path, "nonexistent") == {}

    def test_build_speed_table(self, tmp_path):
        from amta.report.inpaint_ab_report import build_speed_table
        summaries = {
            "baseline": {11: {"avg": 100.0, "n_free": 2}},
            "p0": {11: {"avg": 80.0, "n_free": 2}},
            "p1_cpu": {11: {"avg": 30.0, "n_free": 2}},
            "p1_manga": {11: {"avg": 25.0, "n_free": 2}},
        }
        html = build_speed_table(summaries, pages=[11])
        assert "<table>" in html
        assert "page_11" in html
        assert "100.0s" in html
        assert "平均" in html

    def test_render_returns_html(self, tmp_path):
        from amta.report.inpaint_ab_report import render_inpaint_ab_report
        exp = tmp_path / "exp"
        src = tmp_path / "src"
        src.mkdir()
        Image.new("RGB", (100, 100), "white").save(src / "11.jpg")
        _make_inpaint_summaries(exp)
        html = render_inpaint_ab_report(exp, src, pages=[11])
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html
        assert "速度 A/B" in html

    def test_render_writes_out(self, tmp_path):
        from amta.report.inpaint_ab_report import render_inpaint_ab_report
        exp = tmp_path / "exp"
        src = tmp_path / "src"
        src.mkdir()
        Image.new("RGB", (100, 100), "white").save(src / "11.jpg")
        _make_inpaint_summaries(exp)
        out = tmp_path / "inpaint_ab.html"
        html = render_inpaint_ab_report(exp, src, pages=[11], out_path=out)
        assert out.exists()
        assert out.read_text(encoding="utf-8") == html


# ---------- typeset adapter ----------

class TestTypesetAdapter:
    def test_from_typeset_returns_stageoutput(self):
        from amta.report.stages.typeset import from_typeset
        data = {"layout": {"r0": {"layout_direction": "horizontal",
               "font_size": 18, "lines": ["你好"], "anchor_pos": [50, 30]}}}
        stage = from_typeset(data)
        assert stage.key == "typeset"
        assert stage.label == "排版"
        assert stage.cells["r0"]["font_size"] == 18

    def test_render_cell_shows_text(self):
        from amta.report.stages.typeset import render_cell
        html = render_cell({"layout_direction": "vertical", "font_size": 16,
                            "lines": ["再见"], "anchor_pos": [10, 10]})
        assert "再见" in html and "vertical" in html and "16" in html

    def test_render_cell_empty(self):
        from amta.report.stages.typeset import render_cell
        assert "无" in render_cell(None).lower()


def _make_full_pipeline_artifacts(art_dir, page_idx):
    page = f"page_{page_idx}"
    _make_page_artifacts(art_dir, page_idx)
    Image.new("RGB", (100, 100), (200, 200, 200)).save(art_dir / f"{page}_clean.png")
    (art_dir / f"{page}_inpaint.json").write_text(json.dumps({
        "clean_image": f"{page}_clean.png",
        "masks": {f"r{page_idx}": [[10, 10], [100, 50]]},
        "plan": [{"region_id": f"r{page_idx}", "action": "fill_white",
                  "bbox": [10, 10, 100, 50]}],
    }), encoding="utf-8")
    Image.new("RGB", (100, 100), (240, 240, 240)).save(art_dir / f"{page}_final.png")
    (art_dir / f"{page}_typeset.json").write_text(json.dumps({
        "final_image": f"{page}_final.png",
        "layout": {f"r{page_idx}": {"layout_direction": "horizontal",
                     "font_size": 14, "lines": ["译0"], "anchor_pos": [50, 30]}},
    }), encoding="utf-8")


class TestAssemblerFullPipeline:
    def test_load_page_includes_inpaint_and_typeset(self, tmp_path):
        from amta.report.assembler import load_page_report
        art_dir = tmp_path / "art"; art_dir.mkdir()
        src_dir = tmp_path / "src"
        _make_full_pipeline_artifacts(art_dir, 0)
        _make_raw_image(src_dir, 0)
        page = load_page_report(0, src_dir / "0.jpg",
            detection_path=art_dir / "page_0_detection.json",
            canon_path=art_dir / "page_0_canon.json",
            translation_path=art_dir / "page_0_translation.json",
            inpaint_path=art_dir / "page_0_inpaint.json",
            typeset_path=art_dir / "page_0_typeset.json",
            artifacts_dir=art_dir)
        keys = [s.key for s in page.stages]
        assert "inpaint" in keys and "typeset" in keys

    def test_load_from_workspace_includes_all_stages(self, tmp_path):
        from amta.report.assembler import load_from_workspace
        ws = tmp_path / "workspace" / "tf" / "artifacts"; ws.mkdir(parents=True)
        src_dir = tmp_path / "src"
        _make_full_pipeline_artifacts(ws, 0)
        _make_raw_image(src_dir, 0)
        page = load_from_workspace("tf", 0, src_dir, tmp_path / "workspace")
        keys = [s.key for s in page.stages]
        assert "inpaint" in keys and "typeset" in keys

    def test_missing_inpaint_typeset_skipped(self, tmp_path):
        from amta.report.assembler import load_page_report
        art_dir = tmp_path / "art"; art_dir.mkdir()
        src_dir = tmp_path / "src"
        _make_page_artifacts(art_dir, 0)
        _make_raw_image(src_dir, 0)
        page = load_page_report(0, src_dir / "0.jpg",
            detection_path=art_dir / "page_0_detection.json",
            canon_path=art_dir / "page_0_canon.json",
            translation_path=art_dir / "page_0_translation.json")
        keys = [s.key for s in page.stages]
        assert "inpaint" not in keys and "typeset" not in keys


class TestEngineFullPipeline:
    def test_render_html_has_all_columns(self, tmp_path):
        from amta.report.assembler import load_from_workspace
        from amta.report.engine import render_report
        ws = tmp_path / "workspace" / "tf" / "artifacts"; ws.mkdir(parents=True)
        src_dir = tmp_path / "src"
        _make_full_pipeline_artifacts(ws, 0)
        _make_raw_image(src_dir, 0)
        page = load_from_workspace("tf", 0, src_dir, tmp_path / "workspace")
        result = render_report(page)
        assert "inpaint" in result.html
        assert "排版" in result.html or "typeset" in result.html
        assert "译0" in result.html

    def test_stats_generic_per_stage(self, tmp_path):
        from amta.report.assembler import load_from_workspace
        from amta.report.engine import _compute_stats
        ws = tmp_path / "workspace" / "tf" / "artifacts"; ws.mkdir(parents=True)
        src_dir = tmp_path / "src"
        _make_full_pipeline_artifacts(ws, 0)
        _make_raw_image(src_dir, 0)
        page = load_from_workspace("tf", 0, src_dir, tmp_path / "workspace")
        stats = _compute_stats(page, [])
        stat_labels = [s["lbl"] for s in stats]
        for s in page.stages:
            assert s.label in stat_labels, f"missing stat: {s.label}"

    def test_result_stages_rendered_all(self, tmp_path):
        from amta.report.assembler import load_from_workspace
        from amta.report.engine import render_report
        ws = tmp_path / "workspace" / "tf" / "artifacts"; ws.mkdir(parents=True)
        src_dir = tmp_path / "src"
        _make_full_pipeline_artifacts(ws, 0)
        _make_raw_image(src_dir, 0)
        page = load_from_workspace("tf", 0, src_dir, tmp_path / "workspace")
        result = render_report(page)
        assert "inpaint" in result.stages_rendered
        assert "typeset" in result.stages_rendered



