"""trace_probe 测试：live 定位 / tail 诊断 / stats 统计（纯 stdlib，不依赖真实 ~/.claude）。"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from trace_probe import cmd_live, cmd_stats, cmd_tail  # noqa: E402


def _lines(events: list[dict]) -> list[str]:
    return [json.dumps(x, ensure_ascii=False) for x in events]


def _write(tmp: Path, events: list[dict]) -> Path:
    p = tmp / "session.jsonl"
    p.write_text("\n".join(_lines(events)) + "\n", encoding="utf-8")
    return p


def test_tail_finds_last_tool_use_text_and_result(tmp_path: Path, capsys):
    p = _write(tmp_path, [
        {"type": "system", "timestamp": "2026-09-04T10:00:00Z"},
        {"type": "assistant", "timestamp": "2026-09-04T10:00:01Z", "message": {"content": [
            {"type": "thinking", "thinking": "x"},
            {"type": "tool_use", "name": "Bash", "input": {"command": "echo hi"}},
        ]}},
        {"type": "user", "timestamp": "2026-09-04T10:00:02Z", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "hi", "is_error": False},
        ]}},
        {"type": "assistant", "timestamp": "2026-09-04T10:00:03Z", "message": {"content": [
            {"type": "text", "text": "done"},
        ]}},
    ])
    assert cmd_tail(argparse.Namespace(jsonl=str(p), lines=40)) == 0
    out = capsys.readouterr().out
    assert "last_tool_call: Bash @ 2026-09-04T10:00:01Z" in out
    assert "last_tool_result: is_error=False" in out
    assert "last_text: done" in out


def test_stats_counts_tools_and_repeated_calls(tmp_path: Path, capsys):
    p = _write(tmp_path, [
        {"type": "assistant", "timestamp": "2026-09-04T10:00:00Z", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "uv run python scripts/fastcheck.py"}},
        ]}},
        {"type": "assistant", "timestamp": "2026-09-04T10:00:10Z", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "uv run python scripts/fastcheck.py"}},
        ]}},
        {"type": "assistant", "timestamp": "2026-09-04T10:00:40Z", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "x.py"}},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "x.py"}},
        ]}},
    ])
    assert cmd_stats(argparse.Namespace(jsonl=str(p))) == 0
    out = capsys.readouterr().out
    assert "tool_calls: 4" in out
    assert "Bash=2" in out and "Edit=2" in out
    assert "max_stall_seconds: 30" in out
    assert "repeated_calls: 2" in out


def test_live_picks_newest_after(tmp_path: Path, capsys):
    # 真实布局: projects/<slug>/<uuid>.jsonl —— 必须有一层 slug 子目录
    slug = tmp_path / "proj" / "slug"
    slug.mkdir(parents=True)
    old = slug / "old.jsonl"
    new = slug / "new.jsonl"
    old.write_text("", encoding="utf-8")
    new.write_text("", encoding="utf-8")
    os.utime(old, (_dt.datetime(2026, 9, 4, 10, 0, 0).timestamp(),) * 2)
    os.utime(new, (_dt.datetime(2026, 9, 4, 11, 0, 0).timestamp(),) * 2)
    assert cmd_live(argparse.Namespace(projects_dir=str(tmp_path / "proj"), after="2026-09-04T10:30:00")) == 0
    assert capsys.readouterr().out.strip().endswith("new.jsonl")


def test_live_returns_1_when_nothing_after(tmp_path: Path, capsys):
    slug = tmp_path / "proj" / "slug"
    slug.mkdir(parents=True)
    old = slug / "old.jsonl"
    old.write_text("", encoding="utf-8")
    os.utime(old, (0, 0))
    assert cmd_live(argparse.Namespace(projects_dir=str(tmp_path / "proj"), after="2026-09-04T10:30:00")) == 1
    assert capsys.readouterr().out.strip() == ""


def test_stats_on_missing_file_returns_1(tmp_path: Path, capsys):
    assert cmd_stats(argparse.Namespace(jsonl=str(tmp_path / "nope.jsonl"))) == 1
