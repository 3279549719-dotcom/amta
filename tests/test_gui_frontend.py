"""Run browser state regressions without real models or a browser service."""

import shutil
import subprocess
from pathlib import Path


def test_frontend_page_identity_and_concurrency() -> None:
    node = shutil.which("node")
    assert node, "Node.js is required for the GUI state regression tests"
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", "tests/test_gui_frontend.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
