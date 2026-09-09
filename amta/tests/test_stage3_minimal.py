"""Stage 3 minimal translation — translate_plain + prefetch + entry.

VLM refine 已移除（2026-09-09），归档见 archive/vlm_refine_stage3_2026-09-09.py。

Covers:
- translate_plain: zero-tools batch translate, 数组契约长度校验
- build_prefetch_context: code-side term/context prefetch
- translate_page_minimal: 1-LLM-call-per-page entry contract
"""
import json


def test_translate_plain_batch():
    """translate_plain sends all regions in ONE call, no tools, parses by position."""
    from amta.translation.translate import translate_plain
    canon = [
        {"region_id": "r01", "baberu_text": "こんにちは"},
        {"region_id": "r02", "baberu_text": "ありがとう"},
    ]
    calls = []
    def fake_llm(messages, tools=None):
        calls.append(messages)
        return json.dumps(["你好", "谢谢"])
    result = translate_plain(canon, fake_llm, system_extra="", context_prefix="")
    assert result == {"r01": "你好", "r02": "谢谢"}
    assert len(calls) == 1, "should make exactly one LLM call"
    assert "こんにちは" in calls[0][1]["content"] and "ありがとう" in calls[0][1]["content"]
    # Q6 实验：输入不再写 r01| 前缀（数组契约按位置绑定，前缀多余且可能被 LLM 抄回）
    assert "r01|" not in calls[0][1]["content"] and "r02|" not in calls[0][1]["content"]


def test_prompt_parts_terms_injected():
    """build_prefetch_context must inject relevant glossary terms into system_extra."""
    from amta.translation.stage3_minimal import build_prefetch_context
    canon = [{"region_id": "r01", "baberu_text": "豊姫様"}]
    work_state = {"terms": {"豊姫": {"translation": "丰姬", "status": "confirmed"}}}
    ctx = build_prefetch_context(canon, work_state, None)
    # 术语预替换（replace_in_canon）后，"豊姫"已被直接替换成"丰姬"进 refined_canon，
    # system_extra 因此为空——这是设计行为（f50985a 后术语走预替换而非 system_extra 注入）
    assert any("丰姬" in r.get("baberu_text", "") for r in ctx["refined_canon"]),         "confirmed term must be pre-replaced into refined_canon"
    assert ctx["system_extra"] == "", "pre-replaced terms leave system_extra empty (by design)"


def test_build_semantic_context_public():
    """build_semantic_context must be importable from stage3_minimal (public, not _private)."""
    from amta.translation.stage3_minimal import build_semantic_context
    assert callable(build_semantic_context)


def test_build_prefetch_context_passthrough():
    """build_prefetch_context with no terms passes canon through unchanged."""
    from amta.translation.stage3_minimal import build_prefetch_context
    canon = [{"region_id": "r01", "baberu_text": "テスト"}]
    ctx = build_prefetch_context(canon, {}, None)
    assert ctx["refined_canon"] == canon
    assert "duplicate_map" not in ctx
    assert "invalid_ids" not in ctx


def test_page_key_normalization():
    """SDD Ruling 1: artifacts.page_key requires int — canon page 字段须先归一化。

    validate_canon 之后再进 translate_page_minimal 的 page 理论上是 int，
    此 helper 是防御层（str "11"/"page_11" 也能归一，不可解析返回空串）。
    """
    from amta.translation.stage3_minimal import _page_to_key
    assert _page_to_key(11) == "page_11"
    assert _page_to_key("11") == "page_11"
    assert _page_to_key("page_11") == "page_11"
    assert _page_to_key(None) == ""


def test_translate_page_minimal_contract():
    """translate_page_minimal returns TranslationArtifact-compatible dict."""
    from amta.translation.stage3_minimal import translate_page_minimal
    canon = {"items": [{"region_id": "r01", "baberu_text": "こんにちは", "page": 11}]}

    def fake_text(messages, tools=None):
        return json.dumps(["你好"])

    result = translate_page_minimal("test-work", canon, llm_text=fake_text)
    assert "translations" in result
    assert result["translations"] == {"r01": "你好"}
    assert "residue" in result
    assert "glossary_violations" in result
    assert "vlm_refine" not in result, "VLM refine 已移除，输出不应包含 vlm_refine 字段"
    assert result["page"] == "page_11"  # Ruling 1: page_key 从 canon page 归一化而来


def test_translate_page_minimal_empty_canon_no_llm_call():
    """SDD Ruling 5: 空区域列表必须在调用 LLM 前短路（Task 2 deferred guard）。"""
    from amta.translation.stage3_minimal import translate_page_minimal

    def fake_text(messages, tools=None):
        raise AssertionError("LLM must not be called on empty canon")

    result = translate_page_minimal("test-work", {"items": []}, llm_text=fake_text)
    assert result["translations"] == {}
    assert result["residue"] == []


def test_text_chat_temperature_forwarding(monkeypatch):
    """Review Finding A: text_chat must accept temperature — forwarded into the
    request payload when set, absent when None (legacy callers keep provider default)."""
    import amta.backends.chat_client as chat_client
    from amta.translation.translate import text_chat

    payloads = []

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        payloads.append(json)
        return _FakeResp()

    monkeypatch.setattr(chat_client.requests, "post", fake_post)
    text_chat("http://fake", "fake-model", [{"role": "user", "content": "hi"}],
              temperature=0.3)
    assert payloads[0]["temperature"] == 0.3

    text_chat("http://fake", "fake-model", [{"role": "user", "content": "hi"}])
    assert "temperature" not in payloads[1], \
        "temperature must stay absent when not passed (provider default)"


def test_translate_station_minimal_mode():
    """translate_page delegates to stage3_minimal."""
    from amta.translation.translate_station import translate_page
    canon = {"items": [{"region_id": "r01", "baberu_text": "こんにちは", "page": 11}]}
    def fake_text(messages, tools=None):
        return json.dumps(["你好"])
    result = translate_page("test", canon, llm_text=fake_text)
    assert result["translations"] == {"r01": "你好"}


def test_translate_plain_length_mismatch_returns_empty_no_retry():
    """数组契约（8a576d2 后）：长度不符 → 整批空、只调一次 LLM（不重试、不二分）。"""
    from amta.translation.translate import translate_plain
    canon = [{"region_id": f"r{i:02d}", "baberu_text": f"テキスト{i}"} for i in range(4)]
    call_count = [0]
    def fake_llm(messages, tools=None):
        call_count[0] += 1
        # 始终返回长度 2 的数组 → 与 4 条输入不符
        return json.dumps(["訳0", "訳1"])
    result = translate_plain(canon, fake_llm, system_extra="", context_prefix="")
    assert call_count[0] == 1  # 无重试、无二分
    assert len(result) == 4
    assert all(not v for v in result.values())  # 整批为空


def test_translate_plain_empty_canon():
    """translate_plain with empty canon returns empty dict."""
    from amta.translation.translate import translate_plain
    result = translate_plain([], lambda m: "[]", system_extra="", context_prefix="")
    assert result == {}
