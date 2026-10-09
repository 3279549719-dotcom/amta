"""Windows sandbox write-denial diagnostic + fix verification (scoped).

WHY THIS EXISTS
---------------
On this host a DSH-confined child process (pwsh / python spawned under
`workspace-write`) is denied writes under parts of the workspace, even though the
DACL grants Write through DSH's workspace capability SID. Measured cause:

  DSH lowers a confined child's token to Low integrity. The kernel's mandatory
  integrity check (MIC) allows a Low token to write only to objects whose
  mandatory label is <= Low. An object with NO label is treated as Medium, so
  the write is denied REGARDLESS of the DACL's Write ACE.

DSH's `grantWrite()` is supposed to apply the Low label with OI|CI so children
inherit it. Where that never landed, every child created beneath it is born
unlabeled too -- so the defect is self-perpetuating, and restarting the session
does NOT fix it (grantWrite skips when the root's ACE/deny/label already match).

Proven by `differential`: a real confined child, same DACL in both dirs, writes
fine where the label exists and fails with [Errno 13] where it does not.

SCOPE
-----
This tool inspects ONLY the paths passed to it. It never walks the repository.
Earlier versions recursed the whole tree and reported >10k "missing" directories,
almost all of them pytest scratch dirs under output/logs -- that was a false
alarm, not a finding. Prefer `--path` with the exact pipeline targets.

USAGE
-----
  # inspect (read-only) one or more exact paths
  .venv\\Scripts\\python.exe scripts/probes/probe_sandbox_label.py \\
      --path workspace\\gui-1791359445492\\artifacts \\
      --path workspace\\gui-1791359445492\\state

  # apply the Low label (and, where the SACL write is denied, the explicit
  # FullControl ACE that makes the SACL writable) to exactly those paths
  ... --path <dir> --fix

  # prove the mechanism end-to-end with a real confined child on one directory
  ... --differential --path <dir>

Exit 0 = every requested path is labeled/writable; 1 = something is still missing.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"E:\manga translator agent")
CHECKOUT = Path(r"E:\deepseek harness\deepseek-harness-v0.2.0-rc.2")
RUNNER = CHECKOUT / "packages" / "sandbox" / "sandbox-windows-acl" / "lib" / "runner.js"
CAP_SID = "S-1-4-355048588-287049547"  # DSH write capability SID for this workspace
LABEL = "Low Mandatory Level"


def icacls(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["icacls", *args], capture_output=True, text=True, errors="replace"
    )


def has_label(path: Path) -> bool:
    """True when the Low mandatory-integrity label is present (icacls reads the SACL)."""
    return LABEL in icacls(str(path)).stdout


def has_cap_ace(path: Path) -> bool:
    return CAP_SID in icacls(str(path)).stdout


def has_explicit_full(path: Path) -> bool:
    """True when the signed-in user has an EXPLICIT FullControl ACE on this object.

    The label lives in the SACL, and writing a SACL needs SeSecurityPrivilege --
    which this token does not hold. An explicit FullControl ACE is what makes the
    label writable here; inherited group rights are not enough (measured).
    """
    user = os.environ.get("USERNAME", "")
    return f"{user}:(F)" in icacls(str(path)).stdout


def set_low_label(path: Path) -> bool:
    """Apply OI|CI no-write-up Low label. Bounded to this one path unless -r given."""
    return icacls(str(path), "/setintegritylevel", "(OI)(CI)LOW").returncode == 0


def grant_full(path: Path) -> bool:
    user = os.environ.get("USERNAME", "")
    return icacls(str(path), "/grant", f"{user}:(F)").returncode == 0


def sid_for(path: str, temp: bool = False) -> str:
    d = hashlib.sha256((b"temp\0" if temp else b"") + path.encode("utf-8")).digest()
    a = (int.from_bytes(d[0:4], "little") % (2**30 - 1)) + 1
    b = (int.from_bytes(d[4:8], "little") % (2**30 - 1)) + 1
    return f"S-1-4-{a}-{b}" + ("-1" if temp else "")


def run_confined(code: str) -> tuple[int, str]:
    """Run python code inside a real DSH-confined child (Low-integrity token)."""
    if not RUNNER.exists():
        raise SystemExit(f"DSH ACL runner not found: {RUNNER}")
    node = shutil.which("node")
    if node is None:
        raise SystemExit("node not found on PATH")
    temp = Path(subprocess.run(
        ["powershell", "-NoProfile", "-Command", "echo $env:TEMP"],
        capture_output=True, text=True).stdout.strip())
    if not temp.is_dir():
        temp = Path(r"C:\Windows\Temp")
    argv = [
        node, str(RUNNER),
        "--workspace", str(ROOT), "--temp", str(temp), "--mode", "workspace-write",
        "--write-sid", sid_for(str(ROOT)),
        "--temp-write-sid", sid_for(str(temp), temp=True),
        "--", str(ROOT / ".venv" / "Scripts" / "python.exe"), "-c", code,
    ]
    p = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=300)
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))[-300:]


def report(path: Path) -> bool:
    lab, cap, exp = has_label(path), has_cap_ace(path), has_explicit_full(path)
    verdict = "OK" if lab else "NO LABEL => confined writes denied"
    print(f"  {path}")
    print(f"      capACE={cap}  explicitFull={exp}  lowLabel={lab}  -> {verdict}")
    return lab


def differential(directory: Path) -> int:
    """Prove the label is load-bearing: same dir, with and without the label."""
    if not directory.is_dir():
        print(f"  [differential] not a directory: {directory}")
        return 1
    marker = directory / "_label_probe.txt"
    was_labeled = has_label(directory)

    print(f"  [differential] {directory}")
    print(f"      label currently: {was_labeled}")

    # Phase A: as-is.
    code = f"open(r'{marker}','a').close(); print('WROTE-OK')"
    rc_a, out_a = run_confined(code)
    print(f"      confined write as-is      : exit={rc_a} {out_a.strip().splitlines()[-1][:70] if out_a.strip() else ''}")
    if marker.exists():
        marker.unlink()

    # Phase B: with the label (then restore the original state).
    if not was_labeled:
        if not set_low_label(directory):
            print("      could not apply the label (needs the explicit FullControl ACE); use --fix first")
            return 1
    code = f"open(r'{marker}','a').close(); print('WROTE-OK')"
    rc_b, out_b = run_confined(code)
    print(f"      confined write WITH label : exit={rc_b} {out_b.strip().splitlines()[-1][:70] if out_b.strip() else ''}")
    if marker.exists():
        marker.unlink()

    if not was_labeled:
        # Leave the state as we found it only if the caller did not ask to fix.
        print("      (label left in place; re-run without --differential to inspect)")

    print()
    if rc_a != 0 and rc_b == 0:
        print("  CONFIRMED: the Low mandatory label is what gates the confined write.")
        return 0
    if rc_a == 0:
        print("  NOTE: the write already succeeded before the label was applied.")
        return 0
    print("  NOT CONFIRMED: see exits above.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Scoped Windows sandbox label diagnostic.")
    ap.add_argument("--path", action="append", required=True,
                    help="exact file/dir to inspect (repeatable). No tree walking.")
    ap.add_argument("--fix", action="store_true",
                    help="grant the explicit FullControl ACE where needed, then apply the Low label")
    ap.add_argument("--differential", action="store_true",
                    help="prove the label is load-bearing on the FIRST --path with a real confined child")
    a = ap.parse_args()

    paths = [Path(p) if Path(p).is_absolute() else (ROOT / p) for p in a.path]

    print("mode:", "FIX" if a.fix else "inspect")
    print()

    if a.fix:
        for p in paths:
            if not p.exists():
                print(f"  SKIP (missing): {p}")
                continue
            # The SACL write needs an explicit FullControl ACE on this object.
            if not has_explicit_full(p):
                grant_full(p)
            ok = set_low_label(p)
            print(f"  {'LABELED' if ok and has_label(p) else 'FAILED '} {p}")

    print("state:")
    ok = all(report(p) for p in paths if p.exists())

    if a.differential:
        print()
        rc = differential(paths[0])
        return rc

    print()
    print("OK: every requested path carries the Low label." if ok
          else "PROBLEM: some requested path lacks the Low label (confined writes there are denied).")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
