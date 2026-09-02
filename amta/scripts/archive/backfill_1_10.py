"""backfill_1_10 — 1-10 页最终翻译转正到 per-work 产物（方案 B 前置）。

背景：1-10 页（page_0..page_9）的最终翻译在 output/data/translation_ocr_paddle_fc.json
（86 框，含导演修订 revisions），但未落成 workspace 产物。00_run_all 的断点续跑 + get_context
前页回溯需要：
  - per-page 产物   workspace/<work_id>/artifacts/page_N_translation.json  （对齐 03 工位契约）
  - 合并单文件       workspace/<work_id>/artifacts/translation.json        （get_context 读取）

用法: python scripts/backfill_1_10.py --work-id touhou-single-wing [--src output/data/translation_ocr_paddle_fc.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.paths import write_json  # noqa: E402
from amta.workstate import ensure_workspace  # noqa: E402

# 页面映射：源图 N.jpg → page_idx = N-1（与 00_run_all 一致）
PAGES = range(0, 10)  # page_0..page_9 = 1..10.jpg


def run(work_id: str, src: Path) -> dict:
    root = ensure_workspace(work_id)
    artifacts = root / "artifacts"
    data = json.loads(src.read_text(encoding="utf-8"))
    trans = data.get("translations", {})
    if not trans:
        raise RuntimeError(f"{src} 无 translations")

    by_page: dict[int, dict[str, str]] = {}
    for rid, t in trans.items():
        m = re.match(r"page_(\d+)_", str(rid))
        if not m:
            continue
        by_page.setdefault(int(m.group(1)), {})[rid] = t

    merged: dict[str, str] = {}
    written = 0
    for p in PAGES:
        page_trans = by_page.get(p, {})
        if not page_trans:
            print(f"[backfill] page_{p}: 无译文，跳过")
            continue
        doc = {"work_id": work_id, "translations": page_trans,
               "residue": [], "glossary_violations": []}
        write_json(artifacts / f"page_{p}_translation.json", doc)
        merged.update(page_trans)
        written += 1

    # 合并单文件（get_context 前页回溯读取）
    write_json(artifacts / "translation.json",
               {"work_id": work_id, "translations": merged,
                "residue": [], "glossary_violations": []})
    print(f"[backfill] {written} 页转正，合并 {len(merged)} 条 -> {artifacts / 'translation.json'}")
    return {"pages": written, "translations": len(merged)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--src", default=str(Path(__file__).resolve().parent.parent
                                          / "output" / "data" / "translation_ocr_paddle_fc.json"))
    a = ap.parse_args()
    run(a.work_id, Path(a.src))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
