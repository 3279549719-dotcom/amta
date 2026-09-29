"""Task contracts, atomic checkpoints and single-writer workspace locking."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def save(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def git(workspace: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(workspace), *args], stderr=subprocess.PIPE)


def validate(config: dict[str, Any]) -> dict[str, Any]:
    for key in ("objective", "acceptance", "workspace"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{key} must be nonempty text")
    for key in ("launcher",):
        _argv(config.get(key))
    if not isinstance(config.get("checks"), list) or not config["checks"]:
        raise ValueError("At least one independent verification command is required")
    for command in config["checks"]:
        _argv(command)
    for key, default in (("max_rounds", 6), ("round_seconds", 300), ("total_seconds", 1800)):
        config.setdefault(key, default)
        if type(config[key]) is not int or config[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    workspace = Path(config["workspace"]).resolve()
    if not (workspace / ".git").is_file():
        raise ValueError("Improvement tasks require a dedicated linked Git worktree")
    if git(workspace, "rev-parse", "--show-superproject-working-tree").strip():
        raise ValueError("A submodule is not a dedicated worktree")
    branch = git(workspace, "branch", "--show-current").decode().strip()
    if branch in ("", "main", "master"):
        raise ValueError("Use a named development branch")
    config["workspace"] = str(workspace)
    return config


def _argv(value: Any) -> None:
    if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x for x in value):
        raise ValueError("Commands must be nonempty arrays of nonempty strings (no shell)")


@contextmanager
def lock(workspace: Path) -> Iterator[None]:
    """OS lock is released on process death; the persistent file is not a stale lock."""
    path = workspace / "workspace" / "agent-runner.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("Another runner owns this workspace") from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def fingerprint(workspace: Path) -> str:
    digest = hashlib.sha256(git(workspace, "rev-parse", "HEAD"))
    digest.update(git(workspace, "diff", "HEAD", "--binary"))
    for raw in git(workspace, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if raw:
            digest.update(raw)
            digest.update((workspace / os.fsdecode(raw)).read_bytes())
    return digest.hexdigest()


def evidence_hashes(workspace: Path, files: Any) -> dict[str, str]:
    if not isinstance(files, list) or not files:
        raise ValueError("Nonempty evidence file list is required")
    result = {}
    for name in files:
        if not isinstance(name, str):
            raise ValueError("Evidence entries must be file paths")
        path = (workspace / name).resolve()
        if not path.is_relative_to(workspace) or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Evidence must be a nonempty file inside the worktree: {name}")
        result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result
