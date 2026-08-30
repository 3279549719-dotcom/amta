"""config 密钥解析测试：env 优先 → .env 回退 → 引号剥离 → 缺失报错（修 F4）。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta import config


def _write_env(tmp_path, lines):
    p = tmp_path / ".env"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_get_chat_config_env_priority(tmp_path, monkeypatch):
    env = _write_env(tmp_path, ['CHAT_BASE_URL="https://dotenv.example"'])
    monkeypatch.setenv("CHAT_BASE_URL", "https://env.example")
    monkeypatch.setenv("CHAT_MODEL", "m1")
    monkeypatch.setenv("CHAT_API_KEY", "sk-1")
    cfg = config.get_chat_config(env_path=env)
    assert cfg["base_url"] == "https://env.example"  # env 优先于 .env
    assert cfg == {"base_url": "https://env.example", "model": "m1", "api_key": "sk-1"}


def test_get_chat_config_dotenv_fallback_and_quotes(tmp_path, monkeypatch):
    monkeypatch.delenv("CHAT_BASE_URL", raising=False)
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    monkeypatch.delenv("CHAT_API_KEY", raising=False)
    env = _write_env(tmp_path, ['CHAT_BASE_URL="https://api.example/v1"',
                                "CHAT_MODEL=m2",
                                "CHAT_API_KEY='sk-2'"])
    cfg = config.get_chat_config(env_path=env)
    assert cfg["base_url"] == "https://api.example/v1"
    assert cfg["api_key"] == "sk-2"  # 引号剥离


def test_get_chat_config_missing_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("CHAT_BASE_URL", raising=False)
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    monkeypatch.delenv("CHAT_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="CHAT_API_KEY"):
        config.get_chat_config(env_path=tmp_path / "missing.env")


def test_get_vlm_api_key_fallback_chain(tmp_path, monkeypatch):
    monkeypatch.delenv("VLM_API_KEY", raising=False)
    monkeypatch.delenv("CHAT_API_KEY", raising=False)
    env = _write_env(tmp_path, ["CHAT_API_KEY=sk-chat"])
    assert config.get_vlm_api_key(env_path=env) == "sk-chat"  # VLM 缺 → CHAT 兜底
    monkeypatch.setenv("VLM_API_KEY", "sk-vlm")
    assert config.get_vlm_api_key(env_path=env) == "sk-vlm"  # VLM 优先
    assert config.get_vlm_api_key(env_path=tmp_path / "no.env") == "sk-vlm"


def test_get_vlm_api_key_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("VLM_API_KEY", raising=False)
    monkeypatch.delenv("CHAT_API_KEY", raising=False)
    assert config.get_vlm_api_key(env_path=tmp_path / "no.env") is None


def test_get_dashscope_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_KEY", raising=False)
    env = _write_env(tmp_path, ["DASHSCOPE_KEY=ds-old"])
    assert config.get_dashscope_key(env_path=env) == "ds-old"  # 兼容旧名
