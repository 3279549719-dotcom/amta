import json, pathlib

import amta  # noqa: F401
base = pathlib.Path("workspace/touhou-getten-shinchi/artifacts/typeset")
for f in sorted(base.glob("page_*.json")):
    if "fingerprint" in f.name: continue
    doc = json.loads(f.read_text(encoding="utf-8"))
    for it in doc.get("rendered_items", []):
        if it.get("layout_direction") == "horizontal":
            text = " / ".join(it.get("lines", []))
            rid = it["region_id"]
            sz = it["font_size"]
            print(f"{f.stem} {rid}: {sz}px | {text}")
