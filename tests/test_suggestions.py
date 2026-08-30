"""suggestions 唯一归属测试：片假名提取 / 追加 / 跨页合并（修 F5）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta import suggestions


def test_extract_katakana_and_stoplist():
    canon = [{"region_id": "page_0_u00", "baberu_text": "サグメはカラ笑った", "page": 0}]
    got = suggestions.SuggestionsExtractor(existing=set()).extract(canon, {"page_0_u00": "译"})
    terms = {s["term"] for s in got}
    assert "サグメ" in terms
    assert "カラ" not in terms  # 语法片假名黑名单


def test_extract_skips_existing():
    canon = [{"region_id": "page_0_u00", "baberu_text": "サグメ", "page": 0}]
    got = suggestions.SuggestionsExtractor(existing={"サグメ"}).extract(canon, {})
    assert got == []


def test_append_suggestions(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    p = suggestions.append_suggestions(state, "w1", [{"term": "サグメ"}])
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["work_id"] == "w1" and doc["suggestions"] == [{"term": "サグメ"}]
    suggestions.append_suggestions(state, "w1", [{"term": "第二"}])
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert len(doc["suggestions"]) == 2  # 追加不覆盖


def test_merge_into_state_cross_page_confirmed():
    state = {"terms": {"已确认": {"translation": "旧", "status": "confirmed"}}}
    out = suggestions.merge_into_state(state, [
        {"term": "サグメ", "translation": "沙谟", "page": 0},
        {"term": "サグメ", "translation": "沙谟", "page": 1},
        {"term": "已确认", "translation": "新译", "page": 2},
    ])
    assert out["terms"]["サグメ"]["status"] == "confirmed"  # ≥2 页且译名一致
    assert out["terms"]["已确认"]["translation"] == "旧"  # 已确认不降级
