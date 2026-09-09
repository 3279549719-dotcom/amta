#!/usr/bin/env python3
"""CLI: pre-scan a work's canon artifacts to build locked terminology dictionary.

Usage:
    python scripts/pre_scan.py --work-id <work_id> --artifacts-dir <path>
    python scripts/pre_scan.py --work-id touhou-single-wing --artifacts-dir workspace/touhou-single-wing/artifacts

Run once per work, before translation (stage 3). Outputs matched term count
and writes confirmed terms to work_state.json.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path for `amta` import
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from amta.guards.pre_scan import run_pre_scan  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-scan canon artifacts to build locked terminology dictionary.")
    ap.add_argument("--work-id", required=True, help="Work identifier (for work_state path)")
    ap.add_argument("--artifacts-dir", required=True, help="Directory containing page_*_canon.json files")
    ap.add_argument("--master-dict", default=None, help="Path to master dict JSON (default: data/thbwiki_master_dict.json)")
    args = ap.parse_args()

    art_dir = Path(args.artifacts_dir)
    if not art_dir.exists():
        print(f"ERROR: artifacts directory not found: {art_dir}", file=sys.stderr)
        return 1

    matched = run_pre_scan(args.work_id, art_dir, master_dict_path=args.master_dict)

    print(f"Pre-scan complete: {len(matched)} terms locked for work '{args.work_id}'")
    if matched:
        print("Locked terms:")
        for surface, translation in sorted(matched.items()):
            print(f"  {surface} → {translation}")
    else:
        print("No master-dictionary terms found in this work.")
        print("(Terms not in the master dict will be translated freely by the LLM.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
