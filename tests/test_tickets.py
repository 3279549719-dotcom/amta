# -*- coding: utf-8 -*-
"""tickets 工单机制测试（ADR-017）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _store(tmp_path, name="tickets.json"):
    from amta.tickets import TicketStore
    return TicketStore(tmp_path / name)


def test_create_open_ticket(tmp_path):
    from amta.tickets import TicketStore
    st = _store(tmp_path)
    t = st.create("w1", "page_2_u08", reason="术语表与评审冲突：咔恰 vs 咔嗒",
                  auto_rounds=3, source="カチャ", translation="咔恰")
    assert t["status"] == "open"
    assert t["kind"] == "term_conflict"  # 关键词分类
    assert st.get(t["id"])["region_id"] == "page_2_u08"
    assert len(st.list_open()) == 1
    # 持久化
    st2 = TicketStore(tmp_path / "tickets.json")
    assert len(st2.list_open()) == 1


def test_classify_kind():
    from amta.tickets import classify_kind
    assert classify_kind("违反机械护栏：术语 カチャ 中文写法不一致") == "term_conflict"
    assert classify_kind("评审误报：把语境补全当编造") == "false_positive"
    assert classify_kind("主语错，需要人工定稿") == "hard_case"


def test_resolve_appends_case_law(tmp_path):
    import json

    st = _store(tmp_path)
    t = st.create("w1", "page_2_u08", reason="术语表与评审冲突",
                  auto_rounds=3, source="カチャ", translation="咔嗒")
    case_law = tmp_path / "case_law.json"
    st.resolve(t["id"], action="更新术语表 カチャ→咔嗒",
               resolution="术语表校准后自动修复 1 轮通过",
               case_law_path=case_law)
    assert st.get(t["id"])["status"] == "resolved"
    assert st.list_open() == []
    doc = json.loads(case_law.read_text(encoding="utf-8"))
    case = doc["cases"][0]
    assert case["region_id"] == "page_2_u08"
    assert case["verdict"] == "pass"
    assert "术语表校准" in case["lesson"]


def test_reject_appends_case_law_as_false_positive(tmp_path):
    import json

    st = _store(tmp_path)
    t = st.create("w1", "page_7_u05", reason="评审误报：语境补全当编造",
                  auto_rounds=2, source="永琳がよく話すのよ", translation="永琳经常说起你哦")
    case_law = tmp_path / "case_law.json"
    st.reject(t["id"], reason="辉夜在场，语境补全合理", case_law_path=case_law)
    assert st.get(t["id"])["status"] == "rejected"
    doc = json.loads(case_law.read_text(encoding="utf-8"))
    assert doc["cases"][0]["verdict"] == "pass"
    assert "误报" in doc["cases"][0]["lesson"]


def test_set_status_in_progress(tmp_path):
    st = _store(tmp_path)
    t = st.create("w1", "r1", reason="难句", auto_rounds=3)
    st.set_status(t["id"], "in_progress", action="接手")
    t2 = st.get(t["id"])
    assert t2["status"] == "in_progress"
    assert t2["action"] == "接手"
