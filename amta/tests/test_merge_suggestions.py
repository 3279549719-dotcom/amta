import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from amta import workstate as ws
import merge_suggestions as ms


def _state(characters=None, terms=None):
    s = dict(ws.TEMPLATE_WORK_STATE, work_id="w")
    s["characters"] = characters or {}
    s["terms"] = terms or {}
    return s


def test_merge_single_page_stays_candidate():
    state = _state()
    suggs = [{"term": "サグメ", "page": 0, "source": "a", "translation": "探女", "status": "candidate"}]
    out = ms.merge(state, suggs)
    assert out["terms"]["サグメ"]["status"] == "candidate"


def test_merge_cross_page_confirmed():
    state = _state()
    suggs = [
        {"term": "サグメ", "page": 0, "source": "a", "translation": "探女", "status": "candidate"},
        {"term": "サグメ", "page": 1, "source": "b", "translation": "探女", "status": "candidate"},
    ]
    out = ms.merge(state, suggs)
    assert out["terms"]["サグメ"]["status"] == "confirmed"


def test_merge_conflicting_translation_stays_candidate():
    state = _state()
    suggs = [
        {"term": "サグメ", "page": 0, "source": "a", "translation": "探女", "status": "candidate"},
        {"term": "サグメ", "page": 1, "source": "b", "translation": "娑葛", "status": "candidate"},
    ]
    out = ms.merge(state, suggs)
    assert out["terms"]["サグメ"]["status"] == "candidate"


def test_merge_keeps_existing_confirmed():
    state = _state(terms={"サグメ": {"translation": "探女", "status": "confirmed"}})
    suggs = [{"term": "サグメ", "page": 0, "source": "a", "translation": "探女", "status": "candidate"}]
    out = ms.merge(state, suggs)
    assert out["terms"]["サグメ"]["status"] == "confirmed"
