"""workstate.py 测试：workspace 布局 + 三 state 文件 + evidence tracking（ADR-013）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _new_id(prefix: str) -> str:
    import uuid
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_observed_status_in_statuses():
    from amta.common import workstate as ws
    assert "observed" in ws.STATUSES


def test_update_character_observed(tmp_path, monkeypatch):
    from amta.common import workstate as ws
    work_id = "ws-test-observed"
    monkeypatch.setattr(ws, "WORKSPACE", tmp_path)
    ws.init_workspace(work_id)
    ws.update_character(work_id, "サグメ", status="observed", source="page_0")
    state = ws.load_state(work_id)
    assert state["characters"]["サグメ"]["status"] == "observed"


def test_ensure_workspace_creates_subdirs():
    from amta.common import workstate as ws
    wid = _new_id("ws")
    root = ws.ensure_workspace(wid)
    for sub in ("raw", "artifacts", "state"):
        assert (root / sub).is_dir()


def test_init_workspace_writes_empty_state_files():
    from amta.common import workstate as ws
    wid = _new_id("ws")
    root = ws.init_workspace(wid)
    for name in ws.STATE_FILES:
        assert (root / "state" / name).is_file(), name
    # 幂等：再次 init 不报错
    ws.init_workspace(wid)


def test_empty_state_is_deepcopied():
    from amta.common import workstate as ws
    a = ws.empty_state()
    b = ws.empty_state()
    a["work_state.json"]["characters"]["x"] = {}
    assert "x" not in b["work_state.json"]["characters"]


def test_load_save_roundtrip():
    from amta.common import workstate as ws
    wid = _new_id("ws")
    ws.init_workspace(wid)
    state = ws.load_state(wid)
    assert state["work_id"] == wid
    state["characters"]["豊姫"] = {"name": "豊姫", "status": "confirmed", "source": "page_4:text_13"}
    ws.save_state(wid, state)
    assert ws.load_state(wid)["characters"]["豊姫"]["status"] == "confirmed"


def test_add_evidence_fact_with_confidence():
    from amta.common import workstate as ws
    wid = _new_id("ws")
    ws.init_workspace(wid)
    e = ws.add_evidence_fact(wid, "豊姫 distrusts 永琳", status="inferred",
                             source="page_21:text_07", confidence=0.72)
    assert e["status"] == "inferred" and e["confidence"] == 0.72
    assert ws.load_state(wid)["recent_context"][-1]["fact"] == "豊姫 distrusts 永琳"


def test_add_evidence_fact_rejects_bad_status():
    import pytest

    from amta.common import workstate as ws
    wid = _new_id("ws")
    ws.init_workspace(wid)
    with pytest.raises(ValueError):
        ws.add_evidence_fact(wid, "x", status="bogus", source="p")


def test_update_character_upsert():
    from amta.common import workstate as ws
    wid = _new_id("ws")
    ws.init_workspace(wid)
    ws.update_character(wid, "豊姫", source="page_4:text_13", role="disciple")
    ws.update_character(wid, "豊姫", role="disciple", notes="永琳の弟子")
    chars = ws.load_state(wid)["characters"]
    assert chars["豊姫"]["role"] == "disciple"
    assert chars["豊姫"]["notes"] == "永琳の弟子"


def test_add_open_question_increments_id():
    from amta.common import workstate as ws
    wid = _new_id("ws")
    ws.init_workspace(wid)
    ws.add_open_question(wid, "誰が話してる？", raised_page=4)
    q2 = ws.add_open_question(wid, "場所はどこ？", raised_page=5)
    assert q2["id"] == "q2"


def test_validate_state_flags_bad_status():
    from amta.common import workstate as ws
    bad = {"work_id": "w", "characters": {"a": {"status": "nope"}}, "terms": {}, "recent_context": []}
    assert any("invalid status" in p for p in ws.validate_state(bad))
    assert ws.validate_state({"work_id": "w", "characters": {}, "terms": {}, "recent_context": []}) == []
