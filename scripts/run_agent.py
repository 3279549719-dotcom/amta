"""Thin CLI entry point for the project-local improvement agent."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.agent_loop.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
