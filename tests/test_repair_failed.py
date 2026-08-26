# -*- coding: utf-8 -*-
"""repair_failed 自动修复层测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_build_repair_prompt_contains_context():
    from repair_failed import build_repair_prompt
    msgs = build_repair_prompt("r01", "原文です", "旧译文", "主语错，漏译程度词")
    assert "r01" in msgs[0]["content"]
    blob = msgs[1]["content"]
    assert "原文です" in blob
    assert "旧译文" in blob
    assert "主语错" in blob


def test_repair_one_success(monkeypatch):
    from repair_failed import repair_one

    def fake_llm(msgs, tools=None):
        return {"content": '{"r01": "修正译文"}'}

    out = repair_one({}, "r01", "原文", "旧译文", "评审意见",
                     work_state={}, state_dir=None, llm=fake_llm)
    assert out == "修正译文"


def test_repair_one_tool_loop_then_answer(monkeypatch):
    from repair_failed import repair_one
    calls = []

    def fake_llm(msgs, tools=None):
        calls.append(msgs)
        if len(calls) == 1:
            return {"content": None, "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "lookup_term", "arguments": '{"term": "サグメ"}'}}]}
        return {"content": '{"r01": "探女在说话"}', "tool_calls": None}

    ws = {"terms": {"サグメ": {"translation": "探女", "status": "confirmed", "source": "p1"}}}
    out = repair_one({}, "r01", "サグメが話す", "旧译文", "术语不一致",
                     work_state=ws, state_dir=None, llm=fake_llm)
    assert out == "探女在说话"
    assert any(m["role"] == "tool" for m in calls[1])  # 工具结果回传


def test_repair_one_empty_answer_returns_empty():
    from repair_failed import repair_one

    def fake_llm(msgs, tools=None):
        return {"content": "非 JSON 输出", "tool_calls": None}

    out = repair_one({}, "r01", "原文", "旧译文", "评审意见",
                     work_state={}, state_dir=None, llm=fake_llm)
    assert out == ""


def test_run_repairs_failed_and_reruns(tmp_path, monkeypatch):
    import json
    from repair_failed import run

    canon = [{"region_id": "r01", "text": "原文", "page": 0},
             {"region_id": "r02", "text": "别句", "page": 0}]
    (tmp_path / "canon.json").write_text(json.dumps(canon, ensure_ascii=False), encoding="utf-8")

    trans = {"work_id": "w", "translations": {"r01": "旧译文", "r02": "好的译文"}}
    (tmp_path / "translation.json").write_text(json.dumps(trans, ensure_ascii=False), encoding="utf-8")

    sem = {"judged": 2, "passed": 1, "pass_rate": 0.5,
           "failed": [{"region_id": "r01", "source": "原文",
                       "translation": "旧译文", "reason": "主语错"}]}
    (tmp_path / "sem.json").write_text(json.dumps(sem, ensure_ascii=False), encoding="utf-8")

    crops = tmp_path / "crops"
    crops.mkdir()

    def fake_repair_one(cfg, rid, source, old, reason, *, work_state, state_dir, llm=None):
        return "修正译文"

    def fake_rerun(trans_path, canon_path, crops, rid, tmp_out):
        tmp_out.write_text(json.dumps({"judged": 1, "passed": 1, "failed": [], "pass_rate": 1.0}),
                           encoding="utf-8")
        return "pass"

    monkeypatch.setattr("repair_failed.repair_one", fake_repair_one)
    monkeypatch.setattr("repair_failed._rerun_judge", fake_rerun)
    monkeypatch.setattr("repair_failed.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})

    res = run(tmp_path / "canon.json", tmp_path / "translation.json",
              tmp_path / "sem.json", crops, max_rounds=3)
    assert len(res["repaired"]) == 1 and res["repaired"][0]["region_id"] == "r01"
    assert res["needs_review"] == []
    doc = json.loads((tmp_path / "translation.json").read_text(encoding="utf-8"))
    assert doc["translations"]["r01"] == "修正译文"
    assert doc["revisions"][0]["source"] == "auto-repair"


def test_run_rounds_exhausted_marks_needs_review(tmp_path, monkeypatch):
    import json
    from repair_failed import run

    canon = [{"region_id": "r01", "text": "原文", "page": 0}]
    (tmp_path / "canon.json").write_text(json.dumps(canon, ensure_ascii=False), encoding="utf-8")
    trans = {"work_id": "w", "translations": {"r01": "旧译文"}}
    (tmp_path / "translation.json").write_text(json.dumps(trans, ensure_ascii=False), encoding="utf-8")
    sem = {"failed": [{"region_id": "r01", "source": "原文",
                       "translation": "旧译文", "reason": "主语错"}]}
    (tmp_path / "sem.json").write_text(json.dumps(sem, ensure_ascii=False), encoding="utf-8")
    crops = tmp_path / "crops"
    crops.mkdir()

    def fake_repair_one(cfg, rid, source, old, reason, *, work_state, state_dir, llm=None):
        return ""  # 一直修不出

    monkeypatch.setattr("repair_failed.repair_one", fake_repair_one)
    monkeypatch.setattr("repair_failed.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})

    review = tmp_path / "needs_review.json"
    res = run(tmp_path / "canon.json", tmp_path / "translation.json",
              tmp_path / "sem.json", crops, max_rounds=2, out_review=review)
    assert res["repaired"] == []
    assert len(res["needs_review"]) == 1
    assert res["needs_review"][0]["region_id"] == "r01"
    assert review.exists()
