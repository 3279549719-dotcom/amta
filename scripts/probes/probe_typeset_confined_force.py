"""Force a REAL typeset re-run inside a confined child (no cache hit).

Runs run_pipeline.py with --force-rerun scoped to page 1 / typeset only, wrapped
in DSH's ACL runner, so the confined Low-integrity token must actually WRITE:
  artifacts/typeset/page_1.json
  artifacts/final/page_1_final.png
  state/pipeline_log.json
  workspace/books/<id>/meta.json

This is the operation the user's task is about, executed under the same
confinement that previously denied it.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"E:\manga translator agent")
CHECKOUT = Path(r"E:\deepseek harness\deepseek-harness-v0.2.0-rc.2")
RUNNER = CHECKOUT / "packages" / "sandbox" / "sandbox-windows-acl" / "lib" / "runner.js"
NODE = shutil.which("node")

TYPESET = ROOT / "workspace" / "gui-1791359445492" / "artifacts" / "typeset" / "page_1.json"
FINAL = ROOT / "workspace" / "gui-1791359445492" / "artifacts" / "final" / "page_1_final.png"


def sid_for(path: str, temp: bool = False) -> str:
    prefix = b"temp\0" if temp else b""
    d = hashlib.sha256(prefix + path.encode("utf-8")).digest()
    a = (int.from_bytes(d[0:4], "little") % (2**30 - 1)) + 1
    b = (int.from_bytes(d[4:8], "little") % (2**30 - 1)) + 1
    return f"S-1-4-{a}-{b}" + ("-1" if temp else "")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else "MISSING"


def main() -> int:
    temp = Path(subprocess.run(
        ["powershell", "-NoProfile", "-Command", "echo $env:TEMP"],
        capture_output=True, text=True).stdout.strip())
    if not temp.is_dir():
        temp = Path(r"C:\Windows\Temp")

    before = (sha(TYPESET), sha(FINAL))
    print(f"before: typeset={before[0]} final={before[1]}")
    print()

    py = str(ROOT / ".venv" / "Scripts" / "python.exe")
    argv = [
        str(NODE), str(RUNNER),
        "--workspace", str(ROOT),
        "--temp", str(temp),
        "--mode", "workspace-write",
        "--write-sid", sid_for(str(ROOT)),
        "--temp-write-sid", sid_for(str(temp), temp=True),
        "--", py, "scripts/run_pipeline.py",
        "--work-id", "gui-1791359445492",
        "--src-dir", r"workspace\gui-1791359445492\input",
        "--pages", "1",
        "--stages", "typeset",
        "--force-rerun",
    ]

    proc = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                          timeout=600, cwd=str(ROOT))
    out = (proc.stdout or "")
    err = (proc.stderr or "")

    for line in out.splitlines():
        if "typeset" in line or "DONE" in line or "failed" in line.lower():
            print("  " + line.strip())

    after = (sha(TYPESET), sha(FINAL))
    print()
    print(f"after : typeset={after[0]} final={after[1]}")
    print(f"typeset rewritten: {before[0] != after[0]}")
    print(f"final   rewritten: {before[1] != after[1]}")
    print(f"exit code: {proc.returncode}")

    if proc.returncode != 0 and err:
        print("stderr tail:")
        print(err[-800:])

    print()
    if proc.returncode == 0 and before != after:
        print("RESULT: confined typeset re-run WROTE its artifacts successfully.")
        return 0
    print("RESULT: not proven (see above).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
