"""Stage 3 minimal translation — tests for zero-tools batch translate (translate_plain)."""
import json


def test_translate_plain_batch():
    """translate_plain sends all regions in ONE call, no tools, parses by region_id."""
    from amta.translate import translate_plain
    canon = [
        {"region_id": "r01", "baberu_text": "こんにちは"},
        {"region_id": "r02", "baberu_text": "ありがとう"},
    ]
    calls = []
    def fake_llm(messages, tools=None):
        calls.append(messages)
        return json.dumps({"r01": "你好", "r02": "谢谢"})
    result = translate_plain(canon, fake_llm, system_extra="", context_prefix="")
    assert result == {"r01": "你好", "r02": "谢谢"}
    assert len(calls) == 1, "should make exactly one LLM call"
    assert "r01" in calls[0][1]["content"] and "r02" in calls[0][1]["content"]


def test_prompt_parts_terms_injected():
    """_prompt_parts must inject relevant glossary terms and prior context into system/user."""
    from amta.translate import _prompt_parts
    canon = [{"region_id": "r01", "baberu_text": "豊姫様"}]
    work_state = {"terms": {"豊姫": {"translation": "丰姬", "status": "confirmed"}}}
    system, prefix = _prompt_parts(canon, work_state, prev_pages=None, open_questions=None)
    assert "丰姬" in system, "relevant glossary term must be in system message"


def test_build_semantic_context_public():
    """build_semantic_context must be importable from translate_tools (public, not _private)."""
    from amta.translate_tools import build_semantic_context
    assert callable(build_semantic_context)
