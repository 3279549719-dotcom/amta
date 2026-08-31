"""Stage 3 minimal translation — translate_plain + vlm_refine_page + prefetch + entry.

Covers:
- translate_plain (Task 2): zero-tools batch translate
- vlm_refine_page (Task 5): VLM full-page refine, ADVISORY output w/ grounding validation
- build_prefetch_context (Task 5): code-side term/context prefetch
- translate_page_minimal (Task 5): 2-LLM-call-per-page entry contract
"""
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


# ---------- Task 5: stage3_minimal (vlm refine + prefetch + translate entry) ----------


def _write_fake_jpg(tmp_path):
    """vlm_refine_page 需要一个真实存在的图片文件（读字节 → base64）。"""
    img = tmp_path / "page.jpg"
    img.write_bytes(b"\xff\xd8fake-jpeg-bytes")
    return img


def test_vlm_refine_parse(tmp_path):
    """vlm_refine_page parses valid VLM JSON into VlmRefineResult."""
    from amta.stage3_minimal import vlm_refine_page, VlmRefineResult
    canon = [{"region_id": "r01", "baberu_text": "テスト"}]

    def fake_vlm(messages):
        return json.dumps({
            "ocr_refinements": {"r01": "テスト"},
            "bubble_types": {"r01": "dialogue"},
            "scene": "室内测试",
            "invalid_regions": [],
            "duplicate_regions": {},
        })

    result = vlm_refine_page(canon, _write_fake_jpg(tmp_path), fake_vlm)
    assert isinstance(result, VlmRefineResult)
    assert result.scene == "室内测试"
    assert result.ocr_refinements == {"r01": "テスト"}


def test_vlm_refine_invalid_json_returns_none(tmp_path):
    """VLM returning invalid JSON / failing → None (caller uses baberu_text)."""
    from amta.stage3_minimal import vlm_refine_page
    canon = [{"region_id": "r01", "baberu_text": "テスト"}]

    def fake_vlm(messages):
        raise RuntimeError("VLM unavailable")

    result = vlm_refine_page(canon, _write_fake_jpg(tmp_path), fake_vlm)
    assert result is None


def test_vlm_refine_grounding_filters_ungrounded(tmp_path):
    """SDD Ruling 3: VLM output is ADVISORY — empty-string refinements dropped (不抹字),
    ids not present in canon are dropped (grounding validation)."""
    from amta.stage3_minimal import vlm_refine_page
    canon = [{"region_id": "r01", "baberu_text": "テスト"}]

    def fake_vlm(messages):
        return json.dumps({
            "ocr_refinements": {"r01": "", "r99": "幻覚"},  # 空串修正 + 幻觉 id
            "bubble_types": {"r99": "sfx"},
            "scene": "室内",
            "invalid_regions": ["r01", "r99"],  # r99 不在 canon
            "duplicate_regions": {"r01": "r99"},  # 指向不存在的原 region
        })

    result = vlm_refine_page(canon, _write_fake_jpg(tmp_path), fake_vlm)
    assert result is not None
    assert result.ocr_refinements == {}  # 空串丢弃 + r99 幻觉丢弃
    assert result.invalid_regions == ["r01"]  # r99 丢弃
    assert result.duplicate_regions == {}  # 指向不存在 region 的继承丢弃


def test_build_prefetch_context():
    """build_prefetch_context applies VLM refine, filters invalid, marks duplicate."""
    from amta.stage3_minimal import build_prefetch_context, VlmRefineResult
    canon = [
        {"region_id": "r01", "baberu_text": "元のテキスト"},
        {"region_id": "r02", "baberu_text": "重複"},
        {"region_id": "r03", "baberu_text": "ノイズ"},
    ]
    vlm = VlmRefineResult(
        ocr_refinements={"r01": "修正後テキスト"},
        bubble_types={"r01": "dialogue"},
        scene="テスト場面",
        invalid_regions=["r03"],
        duplicate_regions={"r02": "r01"},
    )
    ctx = build_prefetch_context(canon, {}, None, vlm)
    assert ctx["refined_canon"][0]["baberu_text"] == "修正後テキスト"
    assert len(ctx["refined_canon"]) == 2  # r03 filtered out
    assert ctx["duplicate_map"] == {"r02": "r01"}
    assert "テスト場面" in ctx["system_extra"]


def test_page_key_normalization():
    """SDD Ruling 1: artifacts.page_key requires int — canon page 字段须先归一化。

    validate_canon 之后再进 translate_page_minimal 的 page 理论上是 int，
    此 helper 是防御层（str "11"/"page_11" 也能归一，不可解析返回空串）。
    """
    from amta.stage3_minimal import _page_to_key
    assert _page_to_key(11) == "page_11"
    assert _page_to_key("11") == "page_11"
    assert _page_to_key("page_11") == "page_11"
    assert _page_to_key(None) == ""


def test_translate_page_minimal_contract():
    """translate_page_minimal returns TranslationArtifact-compatible dict."""
    from amta.stage3_minimal import translate_page_minimal
    canon = {"items": [{"region_id": "r01", "baberu_text": "こんにちは", "page": 11}]}

    def fake_text(messages, tools=None):
        return json.dumps({"r01": "你好"})

    result = translate_page_minimal("test-work", canon, llm_text=fake_text, vlm_enabled=False)
    assert "translations" in result
    assert result["translations"] == {"r01": "你好"}
    assert "residue" in result
    assert "glossary_violations" in result
    assert result["page"] == "page_11"  # Ruling 1: page_key 从 canon page 归一化而来


def test_translate_page_minimal_empty_canon_no_llm_call():
    """SDD Ruling 5: 空区域列表必须在调用 LLM 前短路（Task 2 deferred guard）。"""
    from amta.stage3_minimal import translate_page_minimal

    def fake_text(messages, tools=None):
        raise AssertionError("LLM must not be called on empty canon")

    result = translate_page_minimal("test-work", {"items": []},
                                    llm_text=fake_text, vlm_enabled=False)
    assert result["translations"] == {}
    assert result["residue"] == []
