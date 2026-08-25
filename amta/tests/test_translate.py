import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_get_chat_config_reads_env(tmp_path, monkeypatch):
    from amta import translate

    env = tmp_path / ".env"
    env.write_text(
        "CHAT_BASE_URL=https://api.deepseek.com\nCHAT_MODEL=deepseek-v4-pro-0813\nCHAT_API_KEY=sk-test\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(translate, "_ENV_PATH", env)
    cfg = translate.get_chat_config()
    assert cfg["base_url"] == "https://api.deepseek.com"
    assert cfg["model"] == "deepseek-v4-pro-0813"
    assert cfg["api_key"] == "sk-test"


def test_text_chat_builds_payload_and_parses(monkeypatch):
    from amta import translate

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=120):
        captured["url"] = url
        captured["json"] = json

        class _R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": "译文"}}]}

        return _R()

    monkeypatch.setattr(translate.requests, "post", fake_post)
    out = translate.text_chat(
        "https://api.deepseek.com", "m", [{"role": "user", "content": "hi"}], api_key="k"
    )
    assert out == "译文"
    assert captured["url"].endswith("/chat/completions")
    assert captured["json"]["messages"] == [{"role": "user", "content": "hi"}]


def test_extract_relevant_terms_partial_match():
    from amta import translate

    glossary = {"豊姫": {"canon_translation": "丰姬"}, "永琳": {"canon_translation": "永琳"}, "月の都": {"canon_translation": "月都"}}
    terms = translate.extract_relevant_terms("豊姫が永琳と話す", glossary)
    assert "豊姫" in terms and "永琳" in terms and "月の都" not in terms


def test_translation_cache_hash_key():
    from amta import translate

    c = translate.TranslationCache()
    c.put("page_1", "原文A", "译文A")
    assert c.get("page_1", "原文A") == "译文A"
    assert c.get("page_1", "原文B") is None


def test_build_prompt_layers():
    import json

    from amta import translate

    canon = [{"region_id": "r01", "text": "豊姫が話す"}]
    ws = {"characters": {"豊姫": {"status": "confirmed", "source": "p4"}}, "terms": {}, "current_scene": {"page": 1}}
    prompt = translate.build_translation_prompt(canon, ws, prev_pages=[], open_questions=[])
    assert "system" in prompt
    assert "豊姫" in json.dumps(prompt, ensure_ascii=False)


def test_mechanical_guardrails_catches_missing_region():
    from amta import translate

    canon = [{"region_id": "r01", "text": "甲"}, {"region_id": "r02", "text": "乙"}]
    translation = {"r01": "译甲"}
    problems = translate.mechanical_guardrails(canon, translation)
    assert any("r02" in p for p in problems)


def test_japanese_residue_detects_kanji():
    from amta import translate

    assert translate.japanese_residue_check(["完全译文", "残り日本語"]) == ["残り日本語"]


def test_translate_with_retry_uses_mechanical_loop():
    from amta import translate

    class _LLM:
        def __init__(self):
            self.calls = 0

        def __call__(self, messages):
            self.calls += 1
            return '{"r01": "译文", "r02": "译文二"}'

    canon = [{"region_id": "r01", "text": "甲"}, {"region_id": "r02", "text": "乙"}]
    llm = _LLM()
    out = translate.translate_with_retry(canon, llm, max_retries=2)
    assert out["r01"] == "译文" and out["r02"] == "译文二"


def test_translate_with_retry_splits_on_failure():
    from amta import translate

    calls = {"n": 0}

    def llm(messages):
        calls["n"] += 1
        return '{"r01": "译文"}' if calls["n"] == 1 else '{"r01": "译文", "r02": "译文二"}'

    canon = [{"region_id": "r01", "text": "甲"}, {"region_id": "r02", "text": "乙"}]
    out = translate.translate_with_retry(canon, llm, max_retries=2)
    assert set(out) == {"r01", "r02"} and calls["n"] >= 2


def test_suggestions_extractor_finds_new_term():
    from amta import translate

    ex = translate.SuggestionsExtractor(existing={"豊姫"})
    canon = [{"region_id": "r01", "text": "稀神サグメが現れた"}]
    suggestions = ex.extract(canon, translations={"r01": "稀神朔姬出现了"})
    assert any("サグメ" in s.get("term", "") for s in suggestions)


def test_translate_with_retry_wires_context_layers():
    """回归：build_translation_prompt 的 Context 分层（Knowledge/History/Uncertainty）必须真进 LLM 消息。"""
    from amta import translate

    captured = {}

    def llm(messages):
        captured["messages"] = messages
        return '{"r01": "译文"}'

    canon = [{"region_id": "r01", "text": "豊姫が話す"}]
    ws = {"characters": {"豊姫": {"status": "confirmed", "source": "p4"}}, "terms": {}}
    prev = [{"page": 1, "translated": "前页译文"}]
    oq = [{"id": "q1", "question": "这个角色是男是女？", "status": "open"}]

    out = translate.translate_with_retry(canon, llm, work_state=ws, prev_pages=prev, open_questions=oq)
    assert out["r01"] == "译文"

    sys_content = captured["messages"][0]["content"]
    usr_content = captured["messages"][1]["content"]
    blob = sys_content + "\n" + usr_content
    assert "豊姫" in blob  # Knowledge 角色
    assert "前页译文" in blob  # History 前页
    assert "男是女" in blob  # Uncertainty 待确认
    assert "r01|豊姫が話す" in usr_content  # Current 当前页块


def test_translate_with_retry_context_reuse_system_in_split():
    """回归：二分拆分时 System/前缀只算一次，分批只换当前块。"""
    from amta import translate

    seen_systems = []
    seen_currents = []

    def llm(messages):
        seen_systems.append(messages[0]["content"])
        seen_currents.append(messages[1]["content"])
        # 单发永远只给 r01（触发拆分）
        return '{"r01": "译文"}'

    canon = [{"region_id": "r01", "text": "甲"}, {"region_id": "r02", "text": "乙"}]
    ws = {"characters": {"豊姫": {"status": "confirmed", "source": "p4"}}}
    out = translate.translate_with_retry(canon, llm, work_state=ws, max_retries=1)
    assert set(out) == {"r01", "r02"}
    # 每批 system 相同（共享整页知识），current 只含该批 region
    assert all(s == seen_systems[0] for s in seen_systems)
    assert "豊姫" in seen_systems[0]
    assert "r01" in seen_currents[0]
    assert "r02" in seen_currents[-1]


def test_cli_translate_uses_llm_and_writes_translation(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from amta import translate
    import json as _json

    canon = [{"region_id": "r01", "text": "豊姫が話す", "page": 1}]
    canon_path = tmp_path / "canon_text.json"
    canon_path.write_text(_json.dumps(canon, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "translation.json"

    # 脚本内 llm 闭包按 text_chat(base_url, model, messages, api_key=...) 调用，fake 须匹配其签名
    def fake_llm(base_url, model, messages, api_key=None):
        return '{"r01": "丰姬在说话"}'

    monkeypatch.setattr(translate, "get_chat_config", lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    monkeypatch.setattr(translate, "text_chat", fake_llm)

    from _03_translate import run

    run(str(canon_path), str(out_path))
    data = _json.loads(out_path.read_text(encoding="utf-8"))
    # run() 落盘信封 {work_id, translations, residue}，译文在 translations 下
    assert data["translations"]["r01"] == "丰姬在说话"
