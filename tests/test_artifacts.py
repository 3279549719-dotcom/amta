"""artifacts 契约层测试：页键/ID 规则、命名、validate、load/save round-trip。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.stores import artifacts


def test_page_key_and_idx_from_raw():
    assert artifacts.page_key(10) == "page_10"
    assert artifacts.page_idx_from_raw(Path("D:/x/11.jpg")) == 11  # 1-based (f50985a)


def test_region_id_single_space():
    assert artifacts.region_id(5, 3) == "page_5_u03"


def test_normalize_region_ids_renames_block_and_parent():
    blocks = [
        {"region_id": "u00", "bbox": [0, 0, 10, 10], "contained_in": None},
        {"region_id": "u01", "bbox": [1, 1, 5, 5], "contained_in": "u00"},
    ]
    out = artifacts.normalize_region_ids(blocks, 7)
    assert out[0]["region_id"] == "page_7_u00"
    assert out[1]["region_id"] == "page_7_u01"
    assert out[1]["contained_in"] == "page_7_u00"  # 父引用同步重写
    assert out[0]["contained_in"] is None


def test_artifact_paths_and_trace(tmp_path):
    paths = artifacts.artifact_paths(tmp_path, "page_0")
    assert paths["detection"] == tmp_path / "detection" / "page_0.json"
    assert paths["canon"] == tmp_path / "canon" / "page_0.json"
    assert paths["crops"] == tmp_path / "crops"
    tp = artifacts.trace_path(tmp_path, "page_0", "01_detect")
    assert tp.name == "page_0_01_detect_trace.json"


def test_write_trace_stamps(tmp_path):
    p = artifacts.write_trace(tmp_path, "page_0", "02_ocr", {"k": 1})
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["station"] == "02_ocr" and doc["page"] == "page_0" and doc["k"] == 1


def _canon_items():
    return [{"region_id": "page_0_u00", "baberu_text": "あ", "vlm_text": None,
             "vlm_status": "ok", "page": 0, "contained_in": None}]


def test_validate_canon_items_ok_and_problems():
    assert artifacts.validate_canon_items(_canon_items()) == []
    bad = [{"region_id": "", "baberu_text": "あ", "page": 0},
           {"region_id": "page_0_u00", "baberu_text": "", "vlm_text": "", "page": 0},
           {"region_id": "page_0_u00", "baberu_text": "あ", "page": "0"},
           {"region_id": "page_0_u00", "baberu_text": "あ", "page": 0, "category": "x"}]
    problems = artifacts.validate_canon_items(bad)
    assert any("missing region_id" in p for p in problems)
    assert any("empty text" in p for p in problems)
    assert any("bad page" in p for p in problems)
    assert any("bad category" in p for p in problems)


def test_canon_roundtrip_doc_shape(tmp_path):
    p = artifacts.save_canon(tmp_path, "page_0", "w1", _canon_items(), vlm_status="ok")
    assert p == tmp_path / "canon" / "page_0.json"
    doc = artifacts.load_canon(p)
    assert doc["work_id"] == "w1" and doc["page"] == "page_0"
    assert doc["schema_version"] == artifacts.SCHEMA_VERSION
    assert doc["n_regions"] == 1 and doc["items"][0]["region_id"] == "page_0_u00"


def test_load_canon_legacy_bare_list(tmp_path):
    p = tmp_path / "page_0_canon.json"
    p.write_text(json.dumps(_canon_items(), ensure_ascii=False), encoding="utf-8")
    doc = artifacts.load_canon(p)  # 旧裸 list → 归一化为 doc
    assert doc["n_regions"] == 1


def test_load_canon_rejects_invalid(tmp_path):
    p = tmp_path / "page_0_canon.json"
    p.write_text(json.dumps([{"region_id": "", "baberu_text": "あ", "page": 0}]), encoding="utf-8")
    with pytest.raises(ValueError, match="region_id"):
        artifacts.load_canon(p)


def test_detection_roundtrip_and_bad_bbox(tmp_path):
    doc = {"work_id": "w", "blocks": [{"region_id": "page_0_u00", "bbox": [0, 0, 5, 5]}],
           "n_boxes": 1}
    p = artifacts.save_detection(tmp_path, "page_0", doc)
    assert artifacts.load_detection(p)["blocks"][0]["region_id"] == "page_0_u00"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"blocks": [{"bbox": [1, 2]}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="bbox"):
        artifacts.load_detection(bad)


def test_translation_roundtrip(tmp_path):
    p = artifacts.save_translation(tmp_path, "page_0", "w", {"page_0_u00": "译"}, [], [])
    doc = artifacts.load_translation(p)
    assert doc["translations"] == {"page_0_u00": "译"}
    assert doc["residue"] == [] and doc["schema_version"] == artifacts.SCHEMA_VERSION
