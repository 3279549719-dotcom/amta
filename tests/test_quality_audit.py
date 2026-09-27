"""quality_audit 红榜测试（friction 2026-09-16 痛点一的回归探针）。

不 mock 阶段函数,直接造最小产物 JSON——红榜的契约就是"读产物文件聚合",
用真文件测试才是真契约。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.orchestrator.quality_audit import audit_page, audit_run, format_redlist


def _make(tmp_path: Path, page: str, *, translation=None, ocr=None, typeset=None):
    """造一页的最小产物。None = 该阶段没跑(无文件)。"""
    art = tmp_path / "artifacts"
    if translation is not None:
        d = art / "translation"; d.mkdir(parents=True, exist_ok=True)
        (d / f"{page}.json").write_text(json.dumps(translation, ensure_ascii=False), encoding="utf-8")
    if ocr is not None:
        d = art / "canon"; d.mkdir(parents=True, exist_ok=True)
        (d / f"{page}.json").write_text(json.dumps(ocr, ensure_ascii=False), encoding="utf-8")
    if typeset is not None:
        d = art / "typeset"; d.mkdir(parents=True, exist_ok=True)
        (d / f"{page}.json").write_text(json.dumps(typeset, ensure_ascii=False), encoding="utf-8")
    return art


def test_all_clean_when_no_artifacts(tmp_path):
    """阶段全没跑 = 无信号,不算异常。"""
    art = _make(tmp_path, "page_1", translation={}, ocr={}, typeset={})
    f = audit_page(art, "page_1")
    assert not f.has_flags
    assert format_redlist([]) == ""


def test_empty_translation_flagged(tmp_path):
    """空译文(值空白)必须上红榜——39 页误删事故的形状。"""
    art = _make(tmp_path, "page_39", translation={"translations": {"r00": "正常", "r09": ""}})
    f = audit_page(art, "page_39")
    assert f.empty_translations == ["r09"]
    assert f.has_flags
    assert "r09" in format_redlist([f])


def test_residue_flagged(tmp_path):
    """残留原文非空串计入条数。"""
    art = _make(tmp_path, "page_40", translation={"translations": {}, "residue": ["", "书名：xxx"]})
    f = audit_page(art, "page_40")
    assert f.residues == 1  # 空串不算


def test_conf_removed_flagged(tmp_path):
    """conf 删框(误删风险)上红榜。"""
    art = _make(tmp_path, "page_17", ocr={"n_conf_removed": 3})
    f = audit_page(art, "page_17")
    assert f.conf_removed == 3


def test_typeset_checks_flagged(tmp_path):
    """typeset checks 四类信号全捕获。"""
    ts = {"checks": {"overflow": ["r02"], "shrunk_bubbles": ["r00", "r01"],
                     "skipped_no_bbox": ["r05"], "coverage_complete": False}}
    art = _make(tmp_path, "page_18", typeset=ts)
    f = audit_page(art, "page_18")
    assert f.overflow == ["r02"]
    assert f.shrunk == ["r00", "r01"]
    assert f.skipped_no_bbox == ["r05"]
    assert f.coverage_incomplete


def test_audit_run_filters_clean_pages(tmp_path):
    """红榜只含有异常的页。"""
    _make(tmp_path, "page_a", translation={"translations": {"r00": "ok"}})
    _make(tmp_path, "page_b", translation={"translations": {"r00": ""}})
    red = audit_run(tmp_path / "artifacts", ["page_a", "page_b"])
    assert [f.page for f in red] == ["page_b"]


def test_corrupt_json_is_silent(tmp_path):
    """损坏的 JSON 静默跳过(未跑/损坏 ≠ 质量异常,不炸红榜)。"""
    d = tmp_path / "artifacts" / "translation"; d.mkdir(parents=True)
    (d / "page_x.json").write_text("{broken", encoding="utf-8")
    f = audit_page(tmp_path / "artifacts", "page_x")
    assert not f.has_flags


def test_legacy_artifacts_use_shared_resolution(tmp_path):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "page_1_canon.json").write_text('{"n_conf_removed": 2}', encoding="utf-8")
    (art / "page_1_translation.json").write_text('{"translations": {"r1": ""}}', encoding="utf-8")
    (art / "page_1_typeset.json").write_text('{"checks": {"overflow": ["r1"]}}', encoding="utf-8")
    flags = audit_page(art, "page_1")
    assert flags.conf_removed == 2
    assert flags.empty_translations == ["r1"]
    assert flags.overflow == ["r1"]
