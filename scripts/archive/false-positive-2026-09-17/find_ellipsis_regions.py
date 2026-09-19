"""找月天所有页面里的纯标点/省略号框。"""
from __future__ import annotations

import json
from pathlib import Path

ws = Path("workspace/touhou-getten-shinchi/artifacts/canon")

for p in range(1, 11):
    f = ws / f"page_{p}.json"
    if not f.exists():
        continue
    with open(f, encoding="utf-8") as fh:
        data = json.load(fh)
    for item in data["items"]:
        text = (item.get("baberu_text") or item.get("text") or "").strip()
        if len(text) > 5 and all(c in ".．。・…" for c in text):
            print(f"page_{p} {item['region_id']}: {repr(text[:80])}")
