"""detect_station 接口测试（FakeKoharu，无真实 koharu server）。"""
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from amta import artifacts
from fakes import FakeKoharu, make_node

PAGE_IDX = 10
PAGE = "page_10"


def _client():
    return FakeKoharu({
        "pp-doclayout-v3": [make_node("a", 0, 0, 40, 20, "あ")],
        "comic-text-detector": [
            make_node("b", 0, 0, 40, 20, "あ"),      # 与 a 重复（IoU=1）
            make_node("c", 60, 60, 30, 30, "い"),
            make_node("d", 62, 62, 10, 8, "い小"),   # 嵌套于 c
        ],
    })


def _detect(tmp_path):
    from amta.detect_station import detect_page
    raw = tmp_path / "11.jpg"
    Image.new("RGB", (200, 100), "white").save(raw)
    art = tmp_path / "artifacts"
    art.mkdir()
    doc = detect_page("w1", raw, art, page_idx=PAGE_IDX, client=_client())
    return doc, art, raw


def test_detect_page_envelope_and_union(tmp_path):
    doc, _, _ = _detect(tmp_path)
    assert doc["page"] == PAGE and doc["work_id"] == "w1"
    assert doc["schema_version"] == artifacts.SCHEMA_VERSION
    assert doc["n_boxes"] == 3  # a/b 去重，c/d 嵌套保留
    assert doc["image_meta"]["width"] == 200
    assert {b["source_engines"][0] for b in doc["blocks"] if b["source_engines"]} <= {
        "pp-doclayout-v3", "comic-text-detector"}


def test_detect_region_id_single_space_and_contained(tmp_path):
    doc, _, _ = _detect(tmp_path)
    ids = {b["region_id"] for b in doc["blocks"]}
    assert ids == {"page_10_u00", "page_10_u01", "page_10_u02"}
    child = next(b for b in doc["blocks"] if b.get("contained_in"))
    assert child["contained_in"] in ids  # 父引用同空间（修 F3）


def test_detect_side_files_written(tmp_path):
    doc, art, _ = _detect(tmp_path)
    paths = artifacts.artifact_paths(art, PAGE)
    assert paths["detection"].exists()
    assert json.loads(paths["detection"].read_text(encoding="utf-8"))["n_boxes"] == 3
    assert artifacts.trace_path(art, PAGE, "01_detect").exists()
    assert (art / f"{PAGE}_detect_raw_engines.json").exists()  # 未去重原始框
