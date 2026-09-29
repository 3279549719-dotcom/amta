"""Exercise the persisted loop and real subprocess boundary without calling a model."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from amta.agent_loop.backend import execute
from amta.agent_loop.runner import accept, create, parse_result, request, resume, run
from amta.agent_loop.state import lock, read, save


@pytest.fixture
def task(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    git("init", "-b", "main")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "init")
    workspace = tmp_path / "work tree"
    git("worktree", "add", "-b", "codex/test", str(workspace))
    (workspace / ".gitignore").write_text("workspace/\n", encoding="utf-8")
    worker = workspace / "worker.py"
    worker.write_text('''import json, re, sys
from pathlib import Path
prompt = Path(sys.argv[-1].removeprefix("Read ").removesuffix(" and execute that task."))
text = prompt.read_text(encoding="utf-8")
nonce = re.search(r"Use this nonce exactly: (\\w+)", text)[1]
response = prompt.parent / "result.json"
round_number = int(prompt.parent.name.split("-")[1])
artifact = Path.cwd() / "workspace" / "evidence.txt"
artifact.write_text("Observed evidence", encoding="utf-8")
result = {"nonce": nonce, "status": "continue" if round_number == 1 else "ready_for_review",
          "summary": "observed", "next_action": "verify", "question": "", "evidence": [str(artifact)]}
response.write_text(json.dumps(result), encoding="utf-8")
''', encoding="utf-8")
    config = {"objective": "Fix a real issue", "acceptance": "Evidence and checks", "workspace": str(workspace),
              "launcher": [sys.executable, str(worker)], "checks": [[sys.executable, "-c", "pass"]],
              "max_rounds": 3, "round_seconds": 10, "total_seconds": 60}
    directory = workspace / "workspace" / "test" / "artifacts" / "agent"
    return directory, config, worker


def test_two_rounds_and_human_acceptance(task):
    directory, config, _ = task
    create(directory, config)
    state = run(directory)
    assert state["round"] == 2
    assert state["status"] == "ready_for_review"
    assert (directory / "round-002" / "checks.json").is_file()
    assert accept(directory)["status"] == "accepted"


def test_check_failure_reaches_budget_with_feedback(task):
    directory, config, _ = task
    config["checks"] = [[sys.executable, "-c", "raise SystemExit(7)"]]
    create(directory, config)
    state = run(directory)
    assert state["status"] == "budget_exhausted"
    assert "Verification failed" in (directory / "round-003" / "request.md").read_text(encoding="utf-8")


def test_empty_successful_backend_is_not_success(task):
    directory, config, _ = task
    config["launcher"] = [sys.executable, "-c", "pass"]
    create(directory, config)
    state = run(directory)
    assert state["status"] == "failed"
    assert state["round"] == 1


@pytest.mark.parametrize("field,value", [("max_rounds", 0), ("round_seconds", True), ("checks", []),
                                        ("objective", ""), ("launcher", "shell string")])
def test_invalid_config(task, field, value):
    directory, config, _ = task
    config[field] = value
    with pytest.raises(ValueError):
        create(directory, config)


def test_stale_result_rejected(tmp_path):
    path = tmp_path / "result.json"
    save(path, {"nonce": "old", "status": "ready_for_review", "summary": "fake"})
    with pytest.raises(ValueError, match="nonce"):
        parse_result(path, "new")


@pytest.mark.parametrize("change", ["code", "evidence"])
def test_accept_rejects_changes(task, change):
    directory, config, worker = task
    create(directory, config)
    run(directory)
    target = worker if change == "code" else Path(config["workspace"]) / "workspace" / "evidence.txt"
    target.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        accept(directory)


def test_human_question_and_resume(task):
    directory, config, worker = task
    worker.write_text(worker.read_text().replace('"continue" if round_number == 1',
                                               '"needs_human" if round_number == 1')
                      .replace('"question": ""', '"question": "Which sample?"'), encoding="utf-8")
    create(directory, config)
    assert run(directory)["status"] == "waiting_for_human"
    resume(directory, "Use sample A")
    assert run(directory)["status"] == "ready_for_review"
    assert "Use sample A" in (directory / "round-002" / "request.md").read_text(encoding="utf-8")


def test_workspace_lock(tmp_path):
    with lock(tmp_path):
        with pytest.raises(ValueError, match="Another runner"):
            with lock(tmp_path):
                pytest.fail("second runner acquired lock")
    with lock(tmp_path):
        pass


def test_timeout_is_failure_and_pid_cleared(tmp_path):
    result = execute([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, tmp_path / "worker", 0.2)
    assert result["timed_out"]
    assert result["returncode"] != 0
    assert not (tmp_path / "worker.pid").exists()


def test_resume_does_not_reset_budget(task):
    directory, config, _ = task
    create(directory, config)
    state = read(directory / "task.json")
    state.update(status="failed", round=2, seconds_used=12)
    save(directory / "task.json", state)
    resumed = resume(directory, "Failure diagnosed")
    assert resumed["round"] == 2
    assert resumed["seconds_used"] == 12


def test_missing_evidence_cannot_pass(task):
    directory, config, worker = task
    worker.write_text(worker.read_text().replace('[str(artifact)]', '[]'), encoding="utf-8")
    create(directory, config)
    assert run(directory)["status"] == "budget_exhausted"


def test_resume_refuses_orphan_child_record(task):
    directory, config, _ = task
    create(directory, config)
    state = read(directory / "task.json")
    state["status"] = "running"
    save(directory / "task.json", state)
    child_dir = directory / "round-001"
    child_dir.mkdir()
    (child_dir / "worker.pid").write_text(str(os.getpid()))
    with pytest.raises(ValueError, match="PID"):
        resume(directory, "recover")


def test_worker_prompt_reserves_fixed_checks_for_supervisor(task):
    directory, config, _ = task
    state = create(directory, config)
    prompt = request(state, "nonce", directory / "result.json")
    assert "Do not run the fixed supervisor checks yourself" in prompt
    assert "Write result.json as your final action" in prompt
