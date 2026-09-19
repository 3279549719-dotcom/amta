"""找所有项目里的纯标点/省略号框。"""
from __future__ import annotations

import json
from pathlib import Path

ws_root = Path("workspace")

for manga_dir in ws_root.iterdir():
    canon_dir = manga_dir / "artifacts" / "canon"
    if not canon_dir.exists():
        continue
    for f in sorted(canon_dir.glob("page_*.json")):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        for item in data.get("items", []):
            text = (item.get("baberu_text") or item.get("text") or "").strip()
            if len(text) > 5 and all(c in ".．。・…" for c in text):
                print(f"{manga_dir.name}/{f.stem} {item['region_id']}: {repr(text[:80])}")
