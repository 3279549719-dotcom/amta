"""Cross-session progress, verification and explicit human acceptance.

DEPRECATED 2026-09-29: This outer runner state machine (queued → running →
verifying → accepted) duplicated DSH's native agent loop. We have migrated to
DSH-native goal + ralph iteration: the model's own agent loop decides when to
stop, run pytest, and report. This module is retained for reference but should
not be invoked from new entry points.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .backend import execute
from .state import evidence_hashes, fingerprint, lock, read, save, validate


def create(directory: Path, config: dict[str, Any]) -> dict:
    config = validate(dict(config))
    workspace = Path(config["workspace"])
    directory = directory.resolve()
    if not directory.is_relative_to(workspace / "workspace"):
        raise ValueError("Task directory must be inside the worktree workspace/ runtime directory")
    with lock(workspace):
        if (directory / "task.json").exists():
            raise ValueError("Task already exists")
        state = {"status": "queued", "round": 0, "seconds_used": 0.0, "history": [],
                 "feedback": "", "config": config}
        save(directory / "task.json", state)
        return state


def request(state: dict, nonce: str, response: Path) -> str:
    config = state["config"]
    return f"""# AMTA improvement task
You are the working agent of a user-authorized local improvement loop.
Work ONLY in {config['workspace']}. Read AGENTS.md and CLAUDE.md first, list
.dsh/skills, then read relevant skills and project memories as needed.
Use existing run_pipeline/peek/artifact/gen_report entry points. One round may
include several tools and a complete experiment. Inspect previous evidence before
repeating work. Use your native image tools to view before/after images when
claiming visual improvement; if unavailable report that limitation honestly.

## Objective
{config['objective']}

## Fixed acceptance criteria
{config['acceptance']}

## Boundaries for this delegated task
Improve the reusable pipeline, never manually patch a final page or translation
to claim success. Do not alter acceptance criteria or runner/config/state files.
Do not merge, push, publish, or run the repository finish/commit workflow; the
supervisor handles delivery after verification. Do not modify original scans,
other worktrees or credentials. Do not spawn background jobs or nested goal loops.
Before returning, finish child commands. Remain within this task's scope.
Do not run the fixed supervisor checks yourself; use focused tests for your
change. The supervisor runs the fixed checks after your process exits. This
avoids paying twice for the same full suite and keeps the round within budget.
Do not add a separate vision model. Unknown visual quality is not a pass.
The task ends for human acceptance; never claim human approval.

## History and supervisor feedback
{json.dumps(state['history'], ensure_ascii=False, indent=2)}
{state['feedback']}

## Output contract
Write result.json as your final action to {response}, using UTF-8 JSON, after
all tools and focused tests finish. Do not call another tool after writing it.
Use this nonce exactly: {nonce}
Schema:
{{"nonce":"{nonce}","status":"continue|ready_for_review|needs_human",
 "summary":"what changed and what you observed",
 "next_action":"concrete next step, required for continue",
 "evidence":["nonempty evidence files inside this worktree"],
 "question":"specific decision if needs_human; otherwise empty"}}
ready_for_review requires actual before/after or diagnostic evidence and an
honest summary. Supervisor will independently run these fixed checks:
{json.dumps(config['checks'], ensure_ascii=False)}
Return needs_human only for a real product choice or a missing external prerequisite.
Runtime round {state['round']} / {config['max_rounds']}, time limit
{config['round_seconds']} seconds. Save useful evidence before the limit.
"""


def parse_result(path: Path, nonce: str) -> dict:
    result = read(path)
    if result.get("nonce") != nonce:
        raise ValueError("Missing or stale round nonce")
    status = result.get("status")
    if status not in ("continue", "ready_for_review", "needs_human"):
        raise ValueError("Invalid worker status")
    if not isinstance(result.get("summary"), str) or not result["summary"].strip():
        raise ValueError("Worker summary is required")
    key = "next_action" if status == "continue" else "question" if status == "needs_human" else None
    if key and (not isinstance(result.get(key), str) or not result[key].strip()):
        raise ValueError(f"{key} is required for {status}")
    return result


def run(directory: Path) -> dict:
    directory = directory.resolve()
    path = directory / "task.json"
    workspace = Path(read(path)["config"]["workspace"])
    with lock(workspace):
        state = read(path)
        config = validate(state["config"])
        if state["status"] not in ("queued",):
            raise ValueError(f"Task is {state['status']}; use status/resume/accept")
        while state["round"] < config["max_rounds"] and state["seconds_used"] < config["total_seconds"]:
            state["round"] += 1
            state["status"] = "running"
            state["started_at"] = time.time()
            save(path, state)
            started = time.monotonic()
            round_dir = directory / f"round-{state['round']:03d}"
            round_dir.mkdir(parents=True, exist_ok=False)
            nonce = uuid.uuid4().hex
            response = round_dir / "result.json"
            prompt = round_dir / "request.md"
            prompt.write_text(request(state, nonce, response), encoding="utf-8")
            try:
                remaining = config["total_seconds"] - state["seconds_used"]
                execution = execute([*config["launcher"], f"Read {prompt} and execute that task."],
                                    workspace, round_dir / "worker", min(config["round_seconds"], remaining))
                save(round_dir / "execution.json", execution)
                if execution["timed_out"] or execution["returncode"] != 0:
                    raise ValueError(f"Worker failed: {execution}; see {round_dir}")
                result = parse_result(response, nonce)
                state["history"].append({"round": state["round"], **result})
                state["feedback"] = ""
                if result["status"] == "needs_human":
                    state["status"] = "waiting_for_human"
                    state["feedback"] = result["question"]
                elif result["status"] == "ready_for_review":
                    state["status"] = "verifying"
                    save(path, state)
                    remaining -= time.monotonic() - started
                    verify(state, workspace, round_dir, result, remaining)
                else:
                    state["status"] = "queued"
            except (OSError, ValueError, RuntimeError) as error:
                state["status"] = "failed"
                state["feedback"] = str(error)
            except BaseException:
                state["status"] = "interrupted"
                state["feedback"] = "Interrupted; inspect logs and workspace before resume"
                raise
            finally:
                state["seconds_used"] += time.monotonic() - started
                save(path, state)
            print(f"round {state['round']}: {state['status']}", flush=True)
            if state["status"] != "queued":
                return state
        state["status"] = "budget_exhausted"
        save(path, state)
        return state


def verify(state: dict, workspace: Path, directory: Path, result: dict, remaining: float) -> None:
    try:
        hashes = evidence_hashes(workspace, result.get("evidence"))
    except ValueError as error:
        state.update(status="queued", feedback=f"Verification failed: {error}")
        return
    before = fingerprint(workspace)
    checks = []
    started = time.monotonic()
    for index, command in enumerate(state["config"]["checks"]):
        budget = remaining - (time.monotonic() - started)
        if budget <= 0:
            state.update(status="budget_exhausted", feedback="No time left for independent checks")
            return
        outcome = execute(command, workspace, directory / f"check-{index}",
                          min(budget, state["config"]["round_seconds"]))
        checks.append({"command": command, **outcome})
        save(directory / "checks.json", {"checks": checks})
        if outcome["timed_out"] or outcome["returncode"] != 0:
            state.update(status="queued", feedback=f"Verification failed. Inspect {directory / 'checks.json'} and logs.")
            return
    if fingerprint(workspace) != before or evidence_hashes(workspace, list(hashes)) != hashes:
        state.update(status="queued", feedback="Checks changed code/evidence; regenerate and verify the final version")
        return
    state.update(status="ready_for_review", review={"fingerprint": before, "evidence": hashes,
                                                   "checks": str(directory / "checks.json")})


def resume(directory: Path, feedback: str) -> dict:
    path = directory / "task.json"
    workspace = Path(read(path)["config"]["workspace"])
    with lock(workspace):
        state = read(path)
        if state["status"] in ("accepted", "ready_for_review", "budget_exhausted", "queued"):
            raise ValueError(f"Cannot resume {state['status']}; create a new scoped task if needed")
        # A supervisor killed outside Python's cleanup may have left a worker alive.
        if list(directory.glob("round-*/*.pid")):
            raise ValueError("Uncleared child PID record: inspect/stop the child before removing its PID file")
        if state["status"] in ("running", "verifying"):
            state["seconds_used"] += max(0, time.time() - state["started_at"])
        if not feedback.strip():
            raise ValueError("Resume requires an explicit recovery observation or human answer")
        state.update(status="queued", feedback=feedback)
        save(path, state)
        return state


def accept(directory: Path) -> dict:
    path = directory / "task.json"
    workspace = Path(read(path)["config"]["workspace"])
    with lock(workspace):
        state = read(path)
        if state["status"] != "ready_for_review":
            raise ValueError("Only ready_for_review can be accepted by the human")
        review = state["review"]
        if fingerprint(workspace) != review["fingerprint"]:
            raise ValueError("Code changed since verification")
        if evidence_hashes(workspace, list(review["evidence"])) != review["evidence"]:
            raise ValueError("Evidence changed since verification")
        state["status"] = "accepted"
        save(path, state)
        return state
