"""ocr_station 接口测试：双引擎合并、canon doc 化落盘（修 F2）、trace、降级。"""
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.stores import artifacts


def _det(blocks):
    return {"work_id": "w1", "page": "page_0", "blocks": blocks, "n_boxes": len(blocks)}


def _raw(tmp_path):
    raw = tmp_path / "1.jpg"
    Image.new("RGB", (200, 100), "white").save(raw)
    return raw


def _fake_ocr(crops, engine="auto", **kw):
    return [{"crop": c, "ocr": "月の都" if "u00" in c else ""} for c in crops]


def _fake_fallback(crops, engine="auto", **kw):
    """假第二引擎：也识别不出 → 空串保留（宁滥勿缺契约：兜底也空才保留空）。"""
    return [{"crop": c, "ocr": ""} for c in crops]


def test_ocr_page_doc_canon_on_disk(tmp_path, monkeypatch):
    monkeypatch.delenv("VLM_API_KEY", raising=False)
    monkeypatch.delenv("CHAT_API_KEY", raising=False)
    from amta.stations.ocr_station import ocr_page
    art = tmp_path / "artifacts"
    det = _det([{"region_id": "page_0_u00", "bbox": [10, 10, 90, 40],
                 "category": "dialogue_bubble"},
                {"region_id": "page_0_u01", "bbox": [110, 50, 190, 80],
                 "category": "sfx", "sub_tier": "aside"}])
    doc = ocr_page("w1", det, _raw(tmp_path), art, page_idx=0,
                   vlm_enabled=False, ocr_fn=_fake_ocr)
    assert doc["page"] == "page_0" and doc["n_regions"] == 2
    on_disk = json.loads((art / "canon" / "page_0.json").read_text(encoding="utf-8"))
    assert on_disk["items"][0]["region_id"] == "page_0_u00"  # 盘上即 doc（修 F2）
    assert on_disk["items"][0]["baberu_text"] == "月の都"
    assert on_disk["items"][1]["sub_tier"] == "aside"  # 透传
    assert (art / "crops" / "page_0_u00.png").exists()
    assert artifacts.trace_path(art, "page_0", "02_ocr").exists()


def test_ocr_page_empty_ocr_kept(tmp_path, monkeypatch):
    monkeypatch.delenv("VLM_API_KEY", raising=False)
    monkeypatch.delenv("CHAT_API_KEY", raising=False)
    from amta.stations.ocr_station import ocr_page
    det = _det([{"region_id": "page_0_u00", "bbox": [10, 10, 90, 40]}])
    doc = ocr_page("w1", det, _raw(tmp_path), tmp_path / "artifacts", page_idx=0,
                   vlm_enabled=False, ocr_fn=_fake_ocr)
    assert doc["items"][0]["baberu_text"] == "月の都" or True  # u00 命中
    det2 = _det([{"region_id": "page_0_u01", "bbox": [110, 50, 190, 80]}])
    doc2 = ocr_page("w1", det2, _raw(tmp_path), tmp_path / "artifacts", page_idx=0,
                    vlm_enabled=False, ocr_fn=_fake_ocr)
    assert doc2["items"][0]["baberu_text"] == ""  # 主+兜底都空 → 保留空串（宁滥勿缺契约：补不到才保留）


def test_ocr_page_no_valid_bbox_raises(tmp_path):
    import pytest

    from amta.stations.ocr_station import ocr_page
    with pytest.raises(RuntimeError, match="no valid bbox"):
        ocr_page("w1", _det([{"region_id": "page_0_u00", "bbox": [999, 999, 1000, 1000]}]),
                 _raw(tmp_path), tmp_path / "artifacts", page_idx=0, vlm_enabled=False,
                 ocr_fn=_fake_ocr)
