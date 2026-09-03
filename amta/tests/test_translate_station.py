"""translate_station 接口测试：minimal 路径唯一入口（legacy 已删除，cleanup commit）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta import artifacts


CANON = [
    {"region_id": "page_0_u00", "baberu_text": "こんにちは", "vlm_text": "こんにちは",
     "vlm_status": "ok", "page": 0, "contained_in": None},
]


def _llm_ok(messages, tools=None):
    return '{"page_0_u00": "你好"}' 


def _state(tmp_path):
    d = tmp_path / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_translate_page_happy_path(tmp_path, monkeypatch):
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translate_station import translate_page
    out = translate_page("w1", CANON, state_dir=_state(tmp_path), page="page_0",
                         llm_text=_llm_ok)
    assert out["translations"]["page_0_u00"] == "你好"
    assert out["residue"] == [] and out["schema_version"] == artifacts.SCHEMA_VERSION


def test_translate_page_accepts_canon_artifact_dict(tmp_path, monkeypatch):
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translate_station import translate_page
    doc = {"items": CANON, "page": "page_0"}
    out = translate_page("w1", doc, state_dir=_state(tmp_path), llm_text=_llm_ok)
    assert out["translations"]["page_0_u00"] == "你好"


def test_translate_page_rejects_bad_canon(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translate_station import translate_page
    with pytest.raises(ValueError, match="canon input schema"):
        translate_page("w1", [{"region_id": "", "baberu_text": "あ", "page": 0}],
                       state_dir=_state(tmp_path), llm_text=_llm_ok)


def test_translate_page_vlm_disabled_no_vlm_call(tmp_path, monkeypatch):
    """vlm_enabled=False skips VLM refine call entirely."""
    call_count = [0]
    def counting_vlm(messages):
        call_count[0] += 1
        return "{}"
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translate_station import translate_page
    out = translate_page("w1", CANON, state_dir=_state(tmp_path), page="page_0",
                         llm_text=_llm_ok, llm_vlm=counting_vlm, vlm_enabled=False)
    assert out["translations"]["page_0_u00"] == "你好"
    assert call_count[0] == 0  # VLM not called when disabled
