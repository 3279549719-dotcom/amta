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
