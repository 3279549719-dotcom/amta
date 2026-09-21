"""A multiline region must remain one array element at the LLM boundary."""
import json

from amta.translation.translate import translate_plain


def test_multiline_regions_have_unambiguous_json_boundaries():
    sources = ['一行目\n二行目「引用」', '別の枠\\末尾']
    canon = [{"region_id": f"r{i}", "text": text} for i, text in enumerate(sources)]

    def llm(messages):
        body = messages[-1]["content"]
        payload = body.split("\n", 1)[1]
        assert json.loads(payload) == sources
        return json.dumps({"translations": ["第一行\n第二行“引用”", "另一框的末尾"]}, ensure_ascii=False)

    result = translate_plain(canon, llm, context_enabled=False)
    assert result == {"r0": "第一行\n第二行“引用”", "r1": "另一框的末尾"}
