"""Run the ORIGINAL failing operation end-to-end, inside a real DSH-confined child.

The original failure was:
    .venv\\Scripts\\python.exe scripts/run_pipeline.py \
        --work-id gui-1791359445492 --src-dir workspace\\gui-1791359445492\\input \
        --pages 1 --stages typeset
failing at book_store.save_meta -> mkdir workspace/books/<id>.

This wraps that exact command in DSH's ACL runner (Low-integrity token,
workspace-write) so the verdict is the kernel's, not an inference.

Exit 0 = the pipeline ran successfully while confined.
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
BOOK_ID = "1f9685aca785b539"


def workspace_sid(path: str) -> str:
    d = hashlib.sha256(path.encode("utf-8")).digest()
    a = (int.from_bytes(d[0:4], "little") % (2**30 - 1)) + 1
    b = (int.from_bytes(d[4:8], "little") % (2**30 - 1)) + 1
    return f"S-1-4-{a}-{b}"


def temp_sid(path: str) -> str:
    d = hashlib.sha256(b"temp\0" + path.encode("utf-8")).digest()
    a = (int.from_bytes(d[0:4], "little") % (2**30 - 1)) + 1
    b = (int.from_bytes(d[4:8], "little") % (2**30 - 1)) + 1
    return f"S-1-4-{a}-{b}-1"


def main() -> int:
    temp = Path(subprocess.run(
        ["powershell", "-NoProfile", "-Command", "echo $env:TEMP"],
        capture_output=True, text=True).stdout.strip())
    if not temp.is_dir():
        temp = Path(r"C:\Windows\Temp")

    py = str(ROOT / ".venv" / "Scripts" / "python.exe")
    argv = [
        str(NODE), str(RUNNER),
        "--workspace", str(ROOT),
        "--temp", str(temp),
        "--mode", "workspace-write",
        "--write-sid", workspace_sid(str(ROOT)),
        "--temp-write-sid", temp_sid(str(temp)),
        "--", py, "scripts/run_pipeline.py",
        "--work-id", "gui-1791359445492",
        "--src-dir", r"workspace\gui-1791359445492\input",
        "--pages", "1",
        "--stages", "typeset",
    ]

    print("command (inside a real DSH-confined child):")
    print("  run_pipeline.py --work-id gui-1791359445492 --pages 1 --stages typeset")
    print()

    proc = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                          timeout=600, cwd=str(ROOT))
    print("---- stdout ----")
    print((proc.stdout or "")[-2500:])
    if proc.stderr:
        print("---- stderr ----")
        print((proc.stderr or "")[-1500:])
    print(f"---- exit code: {proc.returncode} ----")

    if proc.returncode == 0:
        print("RESULT: the original operation SUCCEEDED while confined.")
        return 0
    print("RESULT: the original operation FAILED.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
