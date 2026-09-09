"""tests for scripts/ralph_context.py — Ralph Loop 确定性上下文生成。

设计原则：判断性内容（成果/遗留）由 agent 写进 loop_state，
本模块只做确定性搬运（格式化成注入文本 / DONE commit message）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ralph_context


class TestBuildPreamble:
    """开工注入块：把 memory_index + git_log 拼成 agent 一睁眼就能看到的上下文。"""

    def test_contains_both_memory_index_and_git_log(self):
        pre = ralph_context.build_preamble(
            "L1|foo|docs/lessons.md\nL2|bar|docs/lessons.md",
            "abc123 commit one\ndef456 commit two",
        )
        assert "L1|foo" in pre
        assert "L2|bar" in pre
        assert "abc123 commit one" in pre
        assert "def456 commit two" in pre

    def test_has_section_headers_and_instruction(self):
        pre = ralph_context.build_preamble("idx", "log")
        assert "开工上下文" in pre
        assert "记忆清单" in pre
        assert "git 脉络" in pre
        # 必须告诉 agent 这是外层注入的、要扫一遍挑相关的
        assert "扫" in pre or "挑" in pre or "相关" in pre

    def test_empty_inputs_do_not_crash(self):
        pre = ralph_context.build_preamble("", "")
        assert "开工上下文" in pre


class TestBuildDoneMessage:
    """DONE commit message：从 agent 写好的 loop_state 搬运成果/遗留。"""

    def test_extracts_mission_current_next(self):
        state = {
            "mission": "修复 fastcheck 全部违规",
            "current_step": "修了 8 个 ruff + 14 个 pyright，fastcheck ALL PASS",
            "next_action": "等待人类验收合并回 main",
        }
        msg = ralph_context.build_done_message(state)
        assert "ralph: DONE" in msg
        assert "修复 fastcheck" in msg
        assert "修了 8 个 ruff" in msg
        assert "等待人类验收" in msg

    def test_empty_state_degrades_gracefully(self):
        msg = ralph_context.build_done_message({})
        assert "ralph: DONE" in msg  # 不崩，标签仍在

    def test_partial_state_degrades(self):
        msg = ralph_context.build_done_message({"mission": "只有 mission"})
        assert "只有 mission" in msg
        assert "成果" in msg  # 字段标签仍在，值为空

    def test_long_fields_are_truncated(self):
        state = {"mission": "x" * 500, "current_step": "y" * 500, "next_action": "z" * 500}
        msg = ralph_context.build_done_message(state)
        # commit message 不应过长（单行 < 200 字符级别）
        first_line = msg.splitlines()[0]
        assert len(first_line) < 300


class TestCliDoneMsg:
    """done-msg 子命令：读 loop_state.json 输出 DONE message。"""

    def test_reads_loop_state_from_cwd(self, tmp_path, monkeypatch):
        state = {"mission": "M", "current_step": "C", "next_action": "N"}
        (tmp_path / "loop_state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "ralph_context.py"), "done-msg"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "ralph: DONE" in result.stdout
        assert "M" in result.stdout

    def test_missing_loop_state_exits_nonzero(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # 无 loop_state.json
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "ralph_context.py"), "done-msg"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
