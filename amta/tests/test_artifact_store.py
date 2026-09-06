"""artifact_store 双态测试 — 目录即索引（新布局）+ 旧平铺只读回退。

覆盖 path/legacy_path/resolve/pages/list_files/exists/clear_stage/clear_page，
以及 report 组装对新旧两态均能读（行为等价探针）。
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from amta.artifact_store import JSON_STAGES, ArtifactStore, fingerprint_of, resolve_artifact


def _w(path: Path, data: dict | list | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    else:
        path.write_text(data, encoding="utf-8")


# ---- 路径 ----

def test_path_new_layout():
    store = ArtifactStore(Path("a"))
    assert store.path("canon", "page_2") == Path("a") / "canon" / "page_2.json"
    assert store.path("typeset", "page_11") == Path("a") / "typeset" / "page_11.json"


def test_legacy_path_flat():
    store = ArtifactStore(Path("a"))
    assert store.legacy_path("canon", "page_2") == Path("a") / "page_2_canon.json"
    assert store.legacy_path("typeset", "page_11") == Path("a") / "page_11_typeset.json"


def test_unknown_stage_raises():
    store = ArtifactStore(Path("a"))
    import pytest
    with pytest.raises(KeyError):
        store.legacy_path("bogus", "page_1")


def test_from_artifacts_dir_equivalence():
    a = ArtifactStore("dir")
    b = ArtifactStore.from_artifacts_dir("dir")
    assert a.artifacts_dir == b.artifacts_dir == Path("dir")


# ---- resolve 新→旧回退 ----

def test_resolve_prefers_new_over_legacy(tmp_path):
    art = tmp_path / "artifacts"
    store = ArtifactStore(art)
    _w(store.path("canon", "page_1"), {"new": True})
    _w(store.legacy_path("canon", "page_1"), {"legacy": True})
    p = store.resolve("canon", "page_1")
    assert p == store.path("canon", "page_1")
    assert json.loads(p.read_text(encoding="utf-8")) == {"new": True}
    assert store.exists("canon", "page_1")


def test_resolve_falls_back_to_legacy(tmp_path):
    art = tmp_path / "artifacts"
    store = ArtifactStore(art)
    _w(store.legacy_path("detection", "page_7"), {"legacy": True})
    assert store.resolve("detection", "page_7") == store.legacy_path("detection", "page_7")
    assert store.resolve("detection", "page_8") is None
    assert not store.exists("detection", "page_8")


def test_resolve_artifact_module_helper(tmp_path):
    art = tmp_path / "artifacts"
    _w(art / "page_2_translation.json", {})
    assert resolve_artifact(art, "translation", "page_2") == art / "page_2_translation.json"
    assert resolve_artifact(art, "translation", "page_9") is None


# ---- pages / list_files 双态并集 ----

def test_pages_new_and_legacy_union(tmp_path):
    art = tmp_path / "artifacts"
    store = ArtifactStore(art)
    # 新布局 detection page_1/page_3；旧平铺 detection page_2 + canon page_2
    for page in ("page_1", "page_3"):
        _w(store.path("detection", page), {})
    _w(store.legacy_path("detection", "page_2"), {})
    _w(store.legacy_path("canon", "page_2"), {})
    assert store.pages("detection") == ["page_1", "page_2", "page_3"]
    assert store.pages("canon") == ["page_2"]
    assert store.pages("inpaint") == []


def test_pages_dedup_same_page_both_layouts(tmp_path):
    art = tmp_path / "artifacts"
    store = ArtifactStore(art)
    _w(store.path("canon", "page_1"), {})
    _w(store.legacy_path("canon", "page_1"), {})
    _w(store.legacy_path("canon", "page_2"), {})
    assert store.pages("canon") == ["page_1", "page_2"]


def test_list_files_both_layouts(tmp_path):
    art = tmp_path / "artifacts"
    store = ArtifactStore(art)
    _w(store.path("translation", "page_1"), {})
    _w(store.legacy_path("translation", "page_2"), {})
    files = store.list_files("translation")
    assert store.path("translation", "page_1") in files
    assert store.legacy_path("translation", "page_2") in files
    assert len(files) == 2


def test_pages_sorted_by_page_no_not_lexicographic(tmp_path):
    art = tmp_path / "artifacts"
    store = ArtifactStore(art)
    for page in ("page_2", "page_10", "page_1"):
        _w(store.path("canon", page), {})
    assert store.pages("canon") == ["page_1", "page_2", "page_10"]


# ---- 清理 ----

def test_clear_stage_removes_both_layouts_and_fingerprints(tmp_path):
    art = tmp_path / "artifacts"
    store = ArtifactStore(art)
    _w(store.path("canon", "page_1"), {})
    _w(fingerprint_of(store.path("canon", "page_1")), {})
    _w(store.legacy_path("canon", "page_2"), {})
    _w(fingerprint_of(store.legacy_path("canon", "page_2")), {})
    _w(store.path("detection", "page_1"), {})  # 其它 stage 不受影响
    n = store.clear_stage("canon")
    assert n == 4
    assert not store.exists("canon", "page_1") and not store.exists("canon", "page_2")
    assert not (art / "canon").exists()  # stage 目录清空后移除
    assert store.exists("detection", "page_1")


def test_clear_page_removes_all_stage_products(tmp_path):
    art = tmp_path / "artifacts"
    store = ArtifactStore(art)
    for stage in JSON_STAGES:
        _w(store.path(stage, "page_1"), {})
        _w(fingerprint_of(store.path(stage, "page_1")), {})
    _w(store.legacy_path("typeset", "page_1"), {})  # 旧平铺同页
    _w(store.path("typeset", "page_2"), {})         # 他页不受影响
    n = store.clear_page("page_1")
    # 6 stages × (新布局 artifact + fingerprint) + 旧平铺 typeset artifact 1 个 = 13（仅数产物文件）
    assert n == len(JSON_STAGES) * 2 + 1
    for stage in JSON_STAGES:
        assert not store.exists(stage, "page_1")
    assert store.exists("typeset", "page_2")


# ---- report 双态读（行为等价探针）----

def test_report_assembles_dual_state(tmp_path):
    """旧平铺 2 页 + 新布局 2 页 → load_page_report 都能读。"""
    from amta.report.assembler import load_page_report

    art = tmp_path / "artifacts"
    store = ArtifactStore(art)
    src = tmp_path / "src"
    src.mkdir()
    Image.new("RGB", (40, 40), "white").save(src / "1.jpg")
    Image.new("RGB", (40, 40), "white").save(src / "2.jpg")

    def _doc(page: str, region: str) -> dict:
        return {"work_id": "w", "page": page, "schema_version": "2.1", "n_regions": 1,
                "items": [{"region_id": region, "bbox": [0, 0, 10, 10], "text": "t",
                           "baberu_text": "t", "category": "dialogue_bubble"}]}

    # 新布局：page_1
    _w(store.path("detection", "page_1"), {"page": "page_1", "blocks": [], "n_boxes": 0})
    _w(store.path("canon", "page_1"), _doc("page_1", "page_1_u00"))
    _w(store.path("translation", "page_1"), {"translations": {"page_1_u00": "甲"}})
    # 旧平铺：page_2
    _w(art / "page_2_detection.json", {"page": "page_2", "blocks": [], "n_boxes": 0})
    _w(art / "page_2_canon.json", _doc("page_2", "page_2_u00"))
    _w(art / "page_2_translation.json", {"translations": {"page_2_u00": "乙"}})

    for idx in (1, 2):
        rep = load_page_report(
            page_idx=idx,
            raw_image=src / f"{idx}.jpg",
            detection_path=store.resolve("detection", f"page_{idx}"),
            canon_path=store.resolve("canon", f"page_{idx}"),
            translation_path=store.resolve("translation", f"page_{idx}"),
            artifacts_dir=art,
        )
        assert len(rep.stages) >= 3, f"page_{idx} 应组装 detect/canon/translate 阶段"
    print("dual-state report assembly OK")
