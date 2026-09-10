"""loop_state CLI 测试：update/blocked 走 --root 落到 tmp 目录，不碰真实状态文件。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _run_cli(root: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "loop_state.py"), "--root", str(root), *argv],
        capture_output=True, text=True, encoding="utf-8",
    )


def _load_state(root: Path) -> dict:
    return json.loads((root / "loop_state.json").read_text(encoding="utf-8"))


def test_update_sets_status_blocked(tmp_path: Path):
    r = _run_cli(tmp_path, "update", "--field", "status=BLOCKED", "--field", "escalation=需要人裁决")
    assert r.returncode == 0, r.stderr
    state = _load_state(tmp_path)
    assert state["status"] == "BLOCKED"
    assert state["escalation"] == "需要人裁决"
    assert state["updated_at"]


def test_blocked_shortcut_sets_status_and_escalation(tmp_path: Path):
    r = _run_cli(tmp_path, "blocked", "--reason", "删除文件需人确认")
    assert r.returncode == 0, r.stderr
    state = _load_state(tmp_path)
    assert state["status"] == "BLOCKED"
    assert "删除文件" in state["escalation"]


def test_show_on_empty_root_prints_no_state(tmp_path: Path):
    r = _run_cli(tmp_path, "show")
    assert r.returncode == 0
    assert "无状态" in r.stdout


def test_update_requires_field(tmp_path: Path):
    r = _run_cli(tmp_path, "update")
    assert r.returncode == 1
