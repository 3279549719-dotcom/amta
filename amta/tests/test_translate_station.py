"""translate_station 接口测试：minimal 路径唯一入口（legacy 已删除，cleanup commit）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.stores import artifacts

CANON = [
    {"region_id": "page_0_u00", "baberu_text": "こんにちは", "vlm_text": "こんにちは",
     "vlm_status": "ok", "page": 0, "contained_in": None},
]


def _llm_ok(messages):
    return '["你好"]'


def _state(tmp_path):
    d = tmp_path / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_translate_page_happy_path(tmp_path, monkeypatch):
    monkeypatch.setattr("amta.translation.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translation.translate_station import translate_page
    out = translate_page("w1", CANON, state_dir=_state(tmp_path), page="page_0",
                         llm_text=_llm_ok)
    assert out["translations"]["page_0_u00"] == "你好"
    assert out["residue"] == [] and out["schema_version"] == artifacts.SCHEMA_VERSION


def test_translate_page_accepts_canon_artifact_dict(tmp_path, monkeypatch):
    monkeypatch.setattr("amta.translation.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translation.translate_station import translate_page
    doc = {"items": CANON, "page": "page_0"}
    out = translate_page("w1", doc, state_dir=_state(tmp_path), llm_text=_llm_ok)
    assert out["translations"]["page_0_u00"] == "你好"


def test_translate_page_rejects_bad_canon(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr("amta.translation.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translation.translate_station import translate_page
    with pytest.raises(ValueError, match="canon input schema"):
        translate_page("w1", [{"region_id": "", "baberu_text": "あ", "page": 0}],
                       state_dir=_state(tmp_path), llm_text=_llm_ok)
