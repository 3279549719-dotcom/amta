import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.guards.glossary import check_glossary


def _state(terms=None, characters=None):
    from amta.common import workstate
    s = dict(workstate.TEMPLATE_WORK_STATE, work_id="w")
    s["terms"] = terms or {}
    s["characters"] = characters or {}
    return s


def test_uses_canon_translation_ok():
    ws = _state(terms={"豊姫": {"translation": "丰姬", "status": "confirmed", "aliases": []}})
    canon = [{"region_id": "a", "text": "豊姫が来た", "page": 0}]
    tr = {"a": "丰姬来了"}
    assert check_glossary(canon, tr, ws) == []


def test_detects_canon_residue():
    ws = _state(terms={"豊姫": {"translation": "丰姬", "status": "confirmed", "aliases": []}})
    canon = [{"region_id": "a", "text": "豊姫が来た", "page": 0}]
    tr = {"a": "豊姫来了"}  # 日文残留
    assert check_glossary(canon, tr, ws)


def test_detects_wrong_zh_variant():
    ws = _state(terms={"豊姫": {"translation": "丰姬", "status": "confirmed", "aliases": []}})
    canon = [{"region_id": "a", "text": "豊姫が来た", "page": 0}]
    tr = {"a": "丰妃来了"}  # 与 canon 不同中文写法
    assert check_glossary(canon, tr, ws)


def test_allows_alias():
    ws = _state(terms={"豊姫": {"translation": "丰姬", "status": "confirmed", "aliases": ["丰殿"]}})
    canon = [{"region_id": "a", "text": "豊姫が来た", "page": 0}]
    tr = {"a": "丰殿来了"}
    assert check_glossary(canon, tr, ws) == []


def test_ignores_non_confirmed_terms():
    ws = _state(terms={"豊姫": {"translation": "丰姬", "status": "candidate", "aliases": []}})
    canon = [{"region_id": "a", "text": "豊姫が来た", "page": 0}]
    tr = {"a": "豊姫来了"}
    assert check_glossary(canon, tr, ws) == []


def test_empty_translation_skipped():
    ws = _state(terms={"豊姫": {"translation": "丰姬", "status": "confirmed", "aliases": []}})
    canon = [{"region_id": "a", "text": "豊姫が来た", "page": 0}]
    tr = {"a": ""}
    assert check_glossary(canon, tr, ws) == []
