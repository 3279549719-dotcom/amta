"""合并各 subagent 的 labels 片段到 labels_a.json。

- 容忍 id 带 .png 后缀（如 page_2_cand00.png）或无后缀
- 严格按 manifest 的 id 对齐，缺失的保留 null
- 用法: python scripts/merge_labels.py output/labels_frag/*.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "data"
MANIFEST = OUT / "label_manifest.json"
DEST = OUT / "labels_a.json"


def norm_id(i: str) -> str:
    return i.removesuffix(".png")


def main(argv: list[str]) -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    order = [it["id"] for it in manifest["items"]]
    merged = {oid: {"id": oid, "is_text": None, "cls": None, "confidence": None} for oid in order}

    for f in argv:
        data = json.loads(Path(f).read_text(encoding="utf-8-sig"))
        if not isinstance(data, list):
            print(f"[merge] SKIP (not list): {f}")
            continue
        for item in data:
            oid = norm_id(item.get("id", ""))
            if oid in merged:
                merged[oid] = {
                    "id": oid,
                    "is_text": item.get("is_text"),
                    "cls": item.get("cls"),
                    "confidence": item.get("confidence"),
                }

    result = [merged[oid] for oid in order]
    DEST.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    labeled = sum(1 for r in result if r["is_text"] is not None)
    print(f"[merge] {len(result)} entries, {labeled} labeled, {len(result)-labeled} missing -> {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
