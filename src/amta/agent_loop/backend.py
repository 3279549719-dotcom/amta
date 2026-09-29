"""Bounded shell-free child execution with durable logs and process-tree cleanup."""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path


def execute(command: list[str], workspace: Path, prefix: Path, seconds: float) -> dict:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with prefix.with_suffix(".stdout.log").open("wb") as stdout, prefix.with_suffix(".stderr.log").open("wb") as stderr:
        process = subprocess.Popen(
            command, cwd=workspace, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            shell=False, start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        prefix.with_suffix(".pid").write_text(str(process.pid), encoding="ascii")
        timed_out = False
        try:
            process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate(process)
        except BaseException:
            terminate(process)
            raise
        finally:
            prefix.with_suffix(".pid").unlink(missing_ok=True)
    return {"returncode": process.returncode, "timed_out": timed_out,
            "seconds": time.monotonic() - started}


def terminate(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        process.kill()
    process.wait(timeout=15)
