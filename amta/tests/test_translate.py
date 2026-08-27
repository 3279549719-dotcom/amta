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
    from amta import chat_client, translate

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

    monkeypatch.setattr(chat_client.requests, "post", fake_post)
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
    from amta import translate

    canon = [{"region_id": "r01", "text": "豊姫が話す"}]
    ws = {"characters": {"豊姫": {"status": "confirmed", "source": "p4"}}, "terms": {}, "current_scene": {"page": 1}}
    prompt = translate.build_translation_prompt(canon, ws, prev_pages=[], open_questions=[])
    assert "system" in prompt
    assert "r01|豊姫が話す" in prompt["current"]  # Current 当前页块
    assert "豊姫" not in prompt["system"]  # 最小披露：术语/角色不再预塞（Patrick 裁决）


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


def test_translate_with_retry_minimal_context_disclosure():
    """回归（Patrick 裁决）：Context 最小披露——角色/前页不再预塞，待确认事项保留，当前页块在。"""
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
    assert "豊姫" not in sys_content  # Knowledge 不再预塞（按需 lookup_term）
    assert "前页译文" not in usr_content  # History 不再预塞（按需 get_context）
    assert "男是女" in usr_content  # Uncertainty 待确认保留披露
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
    assert "豊姫" not in seen_systems[0]  # 最小披露：system 不再预塞角色
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

    # 脚本内 llm 闭包按 chat_with_tools(base_url, model, messages, tools=..., api_key=...) 调用，fake 须匹配其签名
    def fake_llm(base_url, model, messages, tools=None, api_key=None):
        return {"content": '{"r01": "丰姬在说话"}'}

    monkeypatch.setattr(translate, "get_chat_config", lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    monkeypatch.setattr(translate, "chat_with_tools", fake_llm)

    from _03_translate import run

    run(str(canon_path), str(out_path))
    data = _json.loads(out_path.read_text(encoding="utf-8"))
    # run() 落盘信封 {work_id, translations, residue}，译文在 translations 下
    assert data["translations"]["r01"] == "丰姬在说话"


def test_run_rejects_bad_canon(monkeypatch, tmp_path):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import json as _json

    from _03_translate import run

    bad = [{"region_id": "a", "text": "x"}]  # 缺 page
    canon_path = tmp_path / "canon.json"
    canon_path.write_text(_json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    try:
        run(str(canon_path), str(tmp_path / "out.json"))
        raise AssertionError("should raise ValueError for bad canon")
    except ValueError as e:
        assert "canon" in str(e).lower()


def test_suggestions_only_katakana_proper_nouns():
    from amta import translate
    ex = translate.SuggestionsExtractor(existing=set())
    canon = [
        {"region_id": "a", "page": 0, "text": "稀神サグメは月が好きだ"},
        {"region_id": "b", "page": 0, "text": "永琳が来た"},
    ]
    tr = {"a": "稀神探女喜欢月亮", "b": "永琳来了"}
    sugg = ex.extract(canon, tr)
    terms = {s["term"] for s in sugg}
    assert "サグメ" in terms            # 片假名专名应提取
    assert "月" not in terms            # 单字不提取
    assert "来た" not in terms          # 普通汉字/动词不提取
    assert "が好き" not in terms        # 不整段提取
    assert "稀神サグメは月が好きだ" not in terms  # 不再整段日文


def test_run_reports_glossary_violation():
    from amta import translate
    canon = [{"region_id": "a", "text": "豊姫が来た", "page": 0}]
    tr = {"a": "豊姫来了"}
    out = translate._run_guardrails_for_test(canon, tr, {"terms": {
        "豊姫": {"translation": "丰姬", "status": "confirmed", "aliases": []}}})
    assert out  # 非空 = 有违例


def test_run_glossary_clean_when_ok():
    from amta import translate
    canon = [{"region_id": "a", "text": "豊姫が来た", "page": 0}]
    tr = {"a": "丰姬来了"}
    out = translate._run_guardrails_for_test(canon, tr, {"terms": {
        "豊姫": {"translation": "丰姬", "status": "confirmed", "aliases": []}}})
    assert out == []


def test_tools_context_lookup_and_prev():
    from amta import translate
    canon = [{"region_id": "a", "text": "サグメは月が好き", "page": 5}]
    ws = {"terms": {"サグメ": {"translation": "探女", "status": "confirmed"}}}
    prev = [{"page": 4, "translated": "前页译文"}]
    ctx = translate.build_tools_context(canon, ws, prev_pages=prev)
    assert "探女" in ctx            # 相关术语预取
    assert "前页译文" in ctx        # 前页上下文
    assert translate.TERM_BUDGET >= 1
    assert translate.VISION_BUDGET == 2


def test_translate_with_retry_injects_tools_ctx(monkeypatch):
    from amta import translate
    seen_system = {}

    def llm(messages):
        seen_system["s"] = messages[0]["content"]
        return '{"r01": "译文"}'

    canon = [{"region_id": "r01", "text": "サグメ", "page": 0}]
    out = translate.translate_with_retry(canon, llm, work_state={"terms": {}},
                                         tools_ctx="工具查得·额外上下文", max_retries=1)
    assert out["r01"] == "译文"
    assert "工具查得·额外上下文" in seen_system["s"]


def test_record_failure_append(tmp_path):
    import json
    from amta import translate
    log = tmp_path / "failure_log.json"
    entry = {"region_id": "a", "reason": "mechanical retry exhausted", "attempts": 3}
    translate.record_failure(log, entry)
    translate.record_failure(log, {"region_id": "b", "reason": "x"})
    doc = json.loads(log.read_text(encoding="utf-8"))
    assert len(doc["failures"]) == 2
    assert doc["failures"][0]["attempts"] == 3


def test_record_failure_overwrites_empty_list(tmp_path):
    import json
    from amta import translate
    log = tmp_path / "failure_log.json"
    translate.record_failure(log, {"region_id": "a", "reason": "x"})
    doc = json.loads(log.read_text(encoding="utf-8"))
    assert doc["failures"] == [{"region_id": "a", "reason": "x"}]
def test_chat_with_tools_passes_tools_payload(monkeypatch):
    from amta import chat_client, translate
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=120):
        captured["json"] = json

        class _R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": "ok"}}]}

        return _R()

    monkeypatch.setattr(chat_client.requests, "post", fake_post)
    out = translate.chat_with_tools(
        "https://api.deepseek.com", "m", [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "lookup_term"}}],
        api_key="k",
    )
    assert out["content"] == "ok"
    assert captured["json"]["tools"] == [{"type": "function", "function": {"name": "lookup_term"}}]


def test_chat_with_tools_parses_tool_calls(monkeypatch):
    from amta import chat_client, translate

    def fake_post(url, headers=None, json=None, timeout=120):
        class _R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {
                    "content": None,
                    "tool_calls": [{"id": "call_1", "type": "function",
                                    "function": {"name": "lookup_term", "arguments": '{"term": "サグメ"}'}}],
                }}]}

        return _R()

    monkeypatch.setattr(chat_client.requests, "post", fake_post)
    out = translate.chat_with_tools("u", "m", [{"role": "user", "content": "hi"}])
    assert out["tool_calls"][0]["function"]["name"] == "lookup_term"


def test_execute_lookup_term_hit_and_miss():
    from amta import translate
    ws = {"terms": {"サグメ": {"translation": "探女", "status": "confirmed", "source": "p1"}},
          "characters": {"永琳": {"translation": "永琳", "status": "confirmed", "source": "p0"}}}
    hit = translate.execute_tool("lookup_term", {"term": "サグメ"}, ws)
    assert "探女" in hit and "confirmed" in hit
    miss = translate.execute_tool("lookup_term", {"term": "存在しない"}, ws)
    assert "未找到" in miss


def test_execute_get_context_from_state_dir(tmp_path):
    import json
    from amta import translate
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "translation.json").write_text(json.dumps({
        "work_id": "w", "translations": {
            "page_0_u01": "第一页译文",
            "page_1_u01": "第二页译文A",
            "page_1_u02": "第二页译文B",
            "page_2_u01": "第三页译文",
        }}, ensure_ascii=False), encoding="utf-8")
    out = translate.execute_tool("get_context", {"pages": 2}, {}, state_dir=state_dir)
    assert "第二页译文A" in out and "第三页译文" in out
    assert "第一页译文" not in out  # 只回溯最近 2 页


def test_translate_with_retry_tool_loop():
    """真工具循环：模型第一轮请求 lookup_term，工具结果回传，第二轮输出译文。"""
    from amta import translate
    calls = []

    def llm(messages, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {"content": None, "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "lookup_term", "arguments": '{"term": "サグメ"}'}}]}
        return {"content": '{"r01": "探女"}', "tool_calls": None}

    canon = [{"region_id": "r01", "text": "サグメ", "page": 0}]
    ws = {"terms": {"サグメ": {"translation": "探女", "status": "confirmed", "source": "p1"}}}
    out = translate.translate_with_retry(canon, llm, work_state=ws, max_retries=1,
                                         tools=translate.TOOLS_SCHEMA)
    assert out["r01"] == "探女"
    roles = [m["role"] for m in calls[1]]
    assert roles == ["system", "user", "assistant", "tool"]  # 工具结果回传
    assert "探女" in calls[1][-1]["content"]


def test_tool_budget_enforced():
    """预算真拦截：一次请求发 TERM_BUDGET+1 个工具调用，最后一个拒绝服务。"""
    from amta import translate
    captured = {}

    def llm(messages, tools=None):
        if "round2" not in captured:
            captured["round2"] = messages
            tcs = [{"id": f"c{i}", "type": "function",
                    "function": {"name": "lookup_term", "arguments": '{"term": "X"}'}}
                   for i in range(translate.TERM_BUDGET + 1)]
            return {"content": None, "tool_calls": tcs}
        return {"content": '{"r01": "译文"}', "tool_calls": None}

    canon = [{"region_id": "r01", "text": "X", "page": 0}]
    out = translate.translate_with_retry(canon, llm, work_state={}, max_retries=1,
                                         tools=translate.TOOLS_SCHEMA)
    assert out["r01"] == "译文"
    tool_msgs = [m for m in captured["round2"] if m["role"] == "tool"]
    assert len(tool_msgs) == translate.TERM_BUDGET + 1
    assert "预算已耗尽" in tool_msgs[-1]["content"]  # 第 11 个被拦截
    assert "未找到术语" in tool_msgs[0]["content"]   # 前 10 个正常执行（查不到）


def test_tool_round_cap():
    """轮次上限：模型一直请求工具不产出 → MAX_TOOL_ROUNDS 强制终止 → 走机械失败路径。"""
    from amta import translate

    def llm(messages, tools=None):
        return {"content": None, "tool_calls": [
            {"id": "c", "type": "function",
             "function": {"name": "lookup_term", "arguments": '{"term": "X"}'}}]}

    canon = [{"region_id": "r01", "text": "X", "page": 0}]
    out = translate.translate_with_retry(canon, llm, work_state={}, max_retries=1,
                                         tools=translate.TOOLS_SCHEMA)
    assert out == {"r01": ""}  # 空译文 = 机械重试失败路径
