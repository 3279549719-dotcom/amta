"""translate_station 接口测试：信封/护栏/failure log/suggestions 全在实现内（修 F8）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta import artifacts


CANON = [
    {"region_id": "page_0_u00", "baberu_text": "こんにちは", "vlm_text": "こんにちは",
     "vlm_status": "ok", "page": 0, "contained_in": None},
]


def _llm_ok(messages, tools=None):
    return {"content": '{"page_0_u00": "你好"}'}


def _llm_always_japanese(messages, tools=None):
    return {"content": '{"page_0_u00": "こんにちは"}'}  # 触发残留护栏 → 重试耗尽


def _state(tmp_path):
    d = tmp_path / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_translate_page_happy_path(tmp_path, monkeypatch):
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translate_station import translate_page
    out = translate_page("w1", CANON, state_dir=_state(tmp_path), page="page_0", llm=_llm_ok)
    assert out["translations"]["page_0_u00"] == "你好"
    assert out["residue"] == [] and out["schema_version"] == artifacts.SCHEMA_VERSION


def test_translate_page_records_failure_log(tmp_path, monkeypatch):
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translate_station import translate_page
    state = _state(tmp_path)
    translate_page("w1", CANON, state_dir=state, page="page_0", llm=_llm_always_japanese)
    log = json.loads((state / "failure_log.json").read_text(encoding="utf-8"))
    kinds = {p["kind"] for p in log["failures"][0]["problems"]}
    assert "residue" in kinds  # 护栏失败结构化落盘（ADR-016）


def test_translate_page_appends_suggestions(tmp_path, monkeypatch):
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translate_station import translate_page
    state = _state(tmp_path)
    canon = [{"region_id": "page_0_u00", "baberu_text": "サグメは言った", "vlm_text": None,
              "vlm_status": "ok", "page": 0}]
    translate_page("w1", canon, state_dir=state, page="page_0", llm=_llm_ok)
    sugg = json.loads((state / "suggestions.json").read_text(encoding="utf-8"))
    assert any(s["term"] == "サグメ" for s in sugg["suggestions"])  # 追加在实现内（修 F5）


def test_translate_page_accepts_canon_artifact_dict(tmp_path, monkeypatch):
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translate_station import translate_page
    doc = {"items": CANON, "page": "page_0"}
    out = translate_page("w1", doc, state_dir=_state(tmp_path), llm=_llm_ok)
    assert out["translations"]["page_0_u00"] == "你好"


def test_translate_page_rejects_bad_canon(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translate_station import translate_page
    with pytest.raises(ValueError, match="canon input schema"):
        translate_page("w1", [{"region_id": "", "baberu_text": "あ", "page": 0}],
                       state_dir=_state(tmp_path), llm=_llm_ok)
