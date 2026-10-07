from amta.guards.name_pre_scan import build_extraction_prompt, parse_extraction_response

def test_prompt_asks_for_json_array():
    text = "スーさんがやってきた。風見幽香もいる。"
    prompt = build_extraction_prompt(text)
    assert "JSON" in prompt
    assert "surface" in prompt
    assert "translation" in prompt

def test_parse_extraction_response_valid():
    raw = '{"names": [{"surface": "スーさん", "translation": "苏桑"}, {"surface": "風見幽香", "translation": "风见幽香"}]}'
    result = parse_extraction_response(raw)
    assert result == {"スーさん": "苏桑", "風見幽香": "风见幽香"}

def test_parse_extraction_response_empty():
    raw = '{"names": []}'
    assert parse_extraction_response(raw) == {}
