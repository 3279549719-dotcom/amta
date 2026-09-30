"""书内翻译记忆：跨页检索、证据留痕、幂等、修订不丢证据。

这些测试在实现前必须全部失败（AttributeError / ImportError）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.common import workstate


def _ws(tmp_path, monkeypatch):
    """把 WORKSPACE 重定向到 tmp，避免污染中央 workspace/。"""
    monkeypatch.setattr(workstate, "WORKSPACE", tmp_path)
    workstate.init_workspace("w1")
    return tmp_path


def test_record_creates_tentative_decision_with_evidence(tmp_path, monkeypatch):
    _ws(tmp_path, monkeypatch)
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
         "page": 2, "region_id": "r05", "match": "exact"},
    ])
    d = workstate.load_decisions("w1")
    assert "ヤミツキ茸" in d
    e = d["ヤミツキ茸"]
    assert e["translation"] == "成瘾菇"
    assert e["status"] == "tentative"
    assert e["source"] == "translate"
    assert e["evidence"] == [
        {"page": 2, "region_id": "r05", "surface_seen": "ヤミツキ茸", "match": "exact"}
    ]


def test_retrieval_ignores_page_distance(tmp_path, monkeypatch):
    """第 3 页记的决定，第 8 页出现时必须命中——页距不存在。"""
    _ws(tmp_path, monkeypatch)
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
         "page": 2, "region_id": "r05", "match": "exact"},
    ])
    page8 = ["そろそろ消費者も現状のヤミツキ茸の合有量に物足りなさがくる頃だろう?"]
    hits = workstate.relevant_decisions("w1", page8)
    assert "ヤミツキ茸" in hits
    assert hits["ヤミツキ茸"]["translation"] == "成瘾菇"


def test_evidence_append_is_idempotent(tmp_path, monkeypatch):
    """同一 (surface, page, region_id) 跑两次，证据不得重复追加。"""
    _ws(tmp_path, monkeypatch)
    ev = {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
          "page": 2, "region_id": "r05", "match": "exact"}
    workstate.record_decisions("w1", [ev])
    workstate.record_decisions("w1", [ev])
    assert len(workstate.load_decisions("w1")["ヤミツキ茸"]["evidence"]) == 1


def test_revision_keeps_old_evidence(tmp_path, monkeypatch):
    _ws(tmp_path, monkeypatch)
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
         "page": 2, "region_id": "r05", "match": "exact"},
    ])
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "迷幻菇", "surface_seen": "ヤミツキ茸",
         "page": 7, "region_id": "r00", "match": "exact"},
    ])
    e = workstate.load_decisions("w1")["ヤミツキ茸"]
    assert e["translation"] == "迷幻菇"          # 新证据生效
    assert len(e["evidence"]) == 2               # 旧证据不丢
    assert e["evidence"][0]["page"] == 2


def test_model_judged_variant_records_alias(tmp_path, monkeypatch):
    _ws(tmp_path, monkeypatch)
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
         "page": 2, "region_id": "r05", "match": "exact"},
    ])
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ",
         "page": 7, "region_id": "r04", "match": "model_judged"},
    ])
    e = workstate.load_decisions("w1")["ヤミツキ茸"]
    assert "ヤミツキ" in e["aliases"]
    assert {x["match"] for x in e["evidence"]} == {"exact", "model_judged"}


def test_terms_take_precedence_and_conflict_is_surfaced(tmp_path, monkeypatch):
    """terms（人工/词典先验）优先于 decisions；冲突不覆盖、要被看见。"""
    _ws(tmp_path, monkeypatch)
    st = workstate.load_state("w1")
    st.setdefault("terms", {})["ヤミツキ茸"] = {
        "translation": "迷幻菇", "status": "confirmed", "source": "pre_scan"}
    workstate.save_state("w1", st)
    workstate.record_decisions("w1", [
        {"surface": "ヤミツキ茸", "translation": "成瘾菇", "surface_seen": "ヤミツキ茸",
         "page": 2, "region_id": "r05", "match": "exact"},
    ])
    hits, conflicts = workstate.relevant_decisions_with_conflicts("w1", ["ヤミツキ茸が"])
    assert hits["ヤミツキ茸"]["translation"] == "迷幻菇"     # terms 优先
    assert conflicts and conflicts[0]["surface"] == "ヤミツキ茸"


def test_corrupt_state_degrades_to_empty_without_raising(tmp_path, monkeypatch):
    _ws(tmp_path, monkeypatch)
    p = tmp_path / "w1" / "state" / "work_state.json"
    p.write_text("{ this is not json", encoding="utf-8")
    assert workstate.load_decisions("w1") == {}
