"""Verify Q6 A/B report and all final images."""
import os
from pathlib import Path

html = Path("workspace/q6-ab-report.html").read_text(encoding="utf-8")
print(f"File size: {len(html)} bytes")
print(f"Has DOCTYPE: {'<!DOCTYPE html>' in html}")
print(f"Has h1: {'<h1' in html}")
print(f"Page sections: {html.count('Page ')}")
print(f"Image tags: {html.count('<img')}")
print(f"Diff tables: {html.count('翻译差异')}")

all_ok = True
for page in [10, 11, 12, 13, 14, 15]:
    for ws in ["ab-prefix-a", "ab-no-prefix-b"]:
        p = f"workspace/{ws}/artifacts/final/page_{page}_final.png"
        exists = os.path.exists(p)
        size = os.path.getsize(p) if exists else 0
        status = "OK" if exists and size > 1000 else "BAD"
        if status != "OK":
            all_ok = False
        print(f"  {ws} p{page}: {status} ({size} bytes)")

print(f"\nALL IMAGES OK: {all_ok}")
