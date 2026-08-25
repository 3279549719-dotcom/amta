import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.canon_schema import validate_canon


def test_valid_canon_no_problems():
    canon = [{"region_id": "page_0_u01", "text": "穢れ", "page": 0},
             {"region_id": "page_0_u02", "text": "月", "page": 0}]
    assert validate_canon(canon) == []


def test_missing_region_id():
    canon = [{"text": "穢れ", "page": 0}]
    assert any("missing region_id" in p for p in validate_canon(canon))


def test_duplicate_region_id():
    canon = [{"region_id": "a", "text": "x", "page": 0},
             {"region_id": "a", "text": "y", "page": 0}]
    assert "duplicate region_id a" in validate_canon(canon)


def test_empty_text():
    canon = [{"region_id": "a", "text": "  ", "page": 0}]
    assert any("empty text" in p for p in validate_canon(canon))


def test_bad_page_type():
    canon = [{"region_id": "a", "text": "x", "page": "zero"}]
    assert any("bad page" in p for p in validate_canon(canon))


def test_not_a_list():
    assert "canon must be a list" in validate_canon({"region_id": "a"})
