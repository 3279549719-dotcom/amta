"""tests/test_memory_inject.py — hook 三态：正常/坏 JSON/空地产 + 瘦包分支。estate fixture 见 conftest。"""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "memory_inject.py"


def _run(estate: Path, stdin_text: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=stdin_text, capture_output=True, text=True, timeout=30,
        cwd=str(estate),
        env={"CLAUDE_PROJECT_DIR": str(estate), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "PATH": os.environ.get("PATH", "")},
        encoding="utf-8", errors="replace",
    )


def test_startup_full_pack(estate: Path):
    r = _run(estate, json.dumps({"session_id": "s1", "source": "startup"}))
    assert r.returncode == 0
    assert "=== AMTA 记忆包 (startup)" in r.stdout
    assert len(r.stdout) <= 1536 + 1  # +1 尾换行


def test_compact_slim_pack(estate: Path):
    r = _run(estate, json.dumps({"session_id": "s1", "source": "compact"}))
    assert r.returncode == 0
    assert "(compact)" in r.stdout
    assert len(r.stdout) <= 512 + 1


def test_bad_json_still_exit0_with_pack(estate: Path):
    r = _run(estate, "not json at all")
    assert r.returncode == 0
    assert "=== AMTA 记忆包" in r.stdout


def test_empty_stdin_falls_back(estate: Path):
    r = _run(estate, "")
    assert r.returncode == 0
    assert "=== AMTA 记忆包" in r.stdout
