"""05_typeset 工位 — clean 图 + canon + translation + detection → final.png + typeset 产物(Stage 5)。

用法: python scripts/05_typeset.py --work-id <id> --canon <canon.json> --trans <translation.json>
      --det <detection.json> --clean <clean.png> --out <page>_typeset.json --final <final.png>
bbox 关联: canon.node_id → detection.blocks[].node_id(零契约改动,ADR-019 不变)。
断点: --out 存在 → 跳过(00_run_all 调用方决定)。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.fonts import resolve_font  # noqa: E402
from amta.paths import read_json, write_json  # noqa: E402
from amta.typeset_engine import decide_direction  # noqa: E402
from amta.typeset_render import render_item  # noqa: E402
from PIL import Image  # noqa: E402


def run(work_id: str, canon_path: Path, trans_path: Path, det_path: Path,
        clean_path: Path, out_path: Path, final_path: Path) -> dict:
    canon = read_json(canon_path)
    trans = read_json(trans_path).get("translations") or {}
    det = read_json(det_path)
    bbox_by_node = {b.get("node_id"): b.get("bbox")
                    for b in (det.get("blocks") or []) if b.get("node_id")}

    img = Image.open(clean_path).convert("RGB")
    rendered_items = []
    skipped_no_bbox = []
    overflow = []
    canon_ids = {c.get("region_id") for c in canon}

    for item in canon:
        rid = item.get("region_id")
        text = trans.get(rid)
        if text is None:
            continue
        bbox = bbox_by_node.get(item.get("node_id"))
        if not bbox:
            skipped_no_bbox.append(rid)
            continue
        category = item.get("category")
        font_path, stroke = resolve_font(category or "dialogue_bubble", text)
        direction = decide_direction(category, bbox, len(text))
        meta = render_item(img, text, str(font_path), bbox, direction, stroke=stroke)
        meta["region_id"] = rid
        meta["font_family"] = font_path.name
        meta["stroke_width"] = stroke
        meta["stroke_color"] = "#FFFFFF"
        meta["text_color"] = "#000000"
        rendered_items.append(meta)
        if meta["font_size"] <= 12 and len("".join(meta.get("lines") or [])) < len(text):
            overflow.append(rid)

    if final_path:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(final_path)

    translated = [rid for rid in trans if rid in canon_ids]
    doc = {
        "work_id": work_id,
        "page": det.get("page", ""),
        "rendered_items": rendered_items,
        "checks": {
            "rendered": len(rendered_items),
            "translated": len(translated),
            "coverage_complete": len(rendered_items) == len(translated),
            "overflow": overflow,
            "skipped_no_bbox": skipped_no_bbox,
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(out_path, doc)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="05_typeset 工位")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--canon", required=True, type=Path)
    ap.add_argument("--trans", required=True, type=Path)
    ap.add_argument("--det", required=True, type=Path)
    ap.add_argument("--clean", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--final", required=True, type=Path)
    a = ap.parse_args()
    doc = run(a.work_id, a.canon, a.trans, a.det, a.clean, a.out, a.final)
    print(f"[05_typeset] {doc['page']}: rendered={doc['checks']['rendered']} "
          f"coverage={doc['checks']['coverage_complete']} "
          f"overflow={len(doc['checks']['overflow'])} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
