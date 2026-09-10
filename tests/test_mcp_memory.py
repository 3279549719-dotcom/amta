"""mcp_memory MCP 字典工具测试：工具清单 / 调用 / 预算 / 协议层。

用 estate fixture（临时地产）覆盖 _root，不触碰真实知识地产。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import mcp_memory


@pytest.fixture(autouse=True)
def _reset_calls():
    """每个用例前重置进程内预算计数器（模块全局跨用例累积）。"""
    mcp_memory._calls = 0
    yield


def _names() -> list[str]:
    return [t["name"] for t in mcp_memory.TOOLS]


def test_tools_list_has_three_dictionary_tools(estate, monkeypatch):
    monkeypatch.setattr(mcp_memory, "_root", estate)
    assert _names() == ["memory_search", "memory_read", "memory_recent"]


def test_memory_search_hits_lesson(estate, monkeypatch):
    monkeypatch.setattr(mcp_memory, "_root", estate)
    text, is_error = mcp_memory.handle_call("memory_search", {"query": "坑"})
    assert is_error is False
    assert "L1|首个坑" in text


def test_memory_search_scope_decisions(estate, monkeypatch):
    monkeypatch.setattr(mcp_memory, "_root", estate)
    text, is_error = mcp_memory.handle_call("memory_search", {"query": "决策", "scope": "decisions"})
    assert is_error is False
    assert "ADR-001" in text


def test_memory_search_multi_token_and(estate, monkeypatch):
    monkeypatch.setattr(mcp_memory, "_root", estate)
    # 多词 AND：两个字须都在同一行出现（L1/L2 各含不同词）
    text, is_error = mcp_memory.handle_call("memory_search", {"query": "教训 预防"})
    assert is_error is False
    assert "L1|首个坑" in text and "L2|第二个坑" in text
    # 第三词不存在 → 无命中（AND 语义）
    text2, is_error2 = mcp_memory.handle_call("memory_search", {"query": "教训 不存在的词xyz"})
    assert is_error2 is False
    assert "无命中" in text2


def test_memory_search_no_hit(estate, monkeypatch):
    monkeypatch.setattr(mcp_memory, "_root", estate)
    text, is_error = mcp_memory.handle_call("memory_search", {"query": "不存在的词xyz"})
    assert is_error is False
    assert "无命中" in text


def test_memory_search_missing_query(estate, monkeypatch):
    monkeypatch.setattr(mcp_memory, "_root", estate)
    text, is_error = mcp_memory.handle_call("memory_search", {})
    assert is_error is True
    assert "需要 query" in text


def test_memory_read_full_entry(estate, monkeypatch):
    monkeypatch.setattr(mcp_memory, "_root", estate)
    text, is_error = mcp_memory.handle_call("memory_read", {"entry": "L1"})
    assert is_error is False
    assert "首个坑" in text
    assert "教训A" in text


def test_memory_read_section(estate, monkeypatch):
    monkeypatch.setattr(mcp_memory, "_root", estate)
    text, is_error = mcp_memory.handle_call("memory_read", {"entry": "L1", "section": "Durable lesson"})
    assert is_error is False
    assert "教训A" in text
    assert "Problem" not in text


def test_memory_read_unknown_entry(estate, monkeypatch):
    monkeypatch.setattr(mcp_memory, "_root", estate)
    text, is_error = mcp_memory.handle_call("memory_read", {"entry": "L99"})
    assert is_error is True
    assert "找不到" in text


def test_memory_recent_has_remember_head(estate, monkeypatch):
    monkeypatch.setattr(mcp_memory, "_root", estate)
    text, is_error = mcp_memory.handle_call("memory_recent", {})
    assert is_error is False
    assert "recent.md" in text


def test_budget_limits_search_calls(estate, monkeypatch):
    monkeypatch.setattr(mcp_memory, "_root", estate)
    monkeypatch.setattr(mcp_memory, "MAX_MEMORY_CALLS", 2)
    mcp_memory._calls = 0
    mcp_memory.handle_call("memory_search", {"query": "坑"})
    mcp_memory.handle_call("memory_search", {"query": "坑"})
    text, is_error = mcp_memory.handle_call("memory_search", {"query": "坑"})
    assert is_error is True
    assert "预算已用尽" in text


def test_budget_does_not_count_recent(estate, monkeypatch):
    monkeypatch.setattr(mcp_memory, "_root", estate)
    monkeypatch.setattr(mcp_memory, "MAX_MEMORY_CALLS", 0)
    mcp_memory._calls = 0
    text, is_error = mcp_memory.handle_call("memory_recent", {})  # recent 不计数
    assert is_error is False
    assert "recent.md" in text


def test_handle_message_initialize(estate, monkeypatch):
    monkeypatch.setattr(mcp_memory, "_root", estate)
    resp = mcp_memory.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["result"]["protocolVersion"] == mcp_memory.PROTOCOL_VERSION
    assert resp["result"]["serverInfo"]["name"] == "amta-memory"


def test_handle_message_tools_list():
    resp = mcp_memory.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert len(resp["result"]["tools"]) == 3


def test_handle_message_tools_call_roundtrip(estate, monkeypatch):
    monkeypatch.setattr(mcp_memory, "_root", estate)
    msg = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "memory_search", "arguments": {"query": "坑"}},
    }
    resp = mcp_memory.handle_message(msg)
    assert resp["id"] == 3
    assert resp["result"]["content"][0]["text"].startswith("L1|")
    assert resp["result"]["isError"] is False


def test_notification_returns_none():
    assert mcp_memory.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_ping_returns_result():
    resp = mcp_memory.handle_message({"jsonrpc": "2.0", "id": 9, "method": "ping"})
    assert resp == {"jsonrpc": "2.0", "id": 9, "result": {}}


def test_unknown_tool_returns_error():
    text, is_error = mcp_memory.handle_call("nope", {})
    assert is_error is True
    assert "未知工具" in text
