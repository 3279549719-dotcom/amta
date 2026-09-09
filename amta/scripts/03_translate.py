"""03_translate 工位 — 读 canon → DeepSeek 翻译 → translation.json（薄 CLI）。

用法: python scripts/03_translate.py --canon <canon.json> --out <translation.json>
      [--work-id ID] [--state-dir DIR] [--raw-image PATH]
实现: amta.translation.translate_station.translate_page（护栏/失败记录/suggestions 全在实现内）。
run() 保留作兼容入口（test_translate / eval_stage3 仍 import run）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.common.paths import write_json
from amta.stores.artifacts import load_canon
from amta.translation.translate_station import translate_page


def run(canon_path: str | Path, out_path: str | Path, *,
        work_id: str | None = None, state_dir: str | Path | None = None,
        raw_image_path: str | Path | None = None) -> dict:
    """读 canon → 翻译 → 落盘 translation.json。"""
    try:
        canon = load_canon(canon_path)  # normalize + validate（旧裸 list 兼容）
    except ValueError as e:
        raise ValueError(f"canon input schema failed: {e}") from e
    out = translate_page(work_id, canon,
                         state_dir=state_dir, page=canon.get("page") or None,
                         raw_image_path=raw_image_path)
    write_json(out_path, out)
    print(f"[03_translate] -> {out_path}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canon", required=True, help="canon.json 路径（doc 或旧裸 list）")
    ap.add_argument("--out", required=True, help="输出 translation.json 路径")
    ap.add_argument("--work-id", default=None)
    ap.add_argument("--state-dir", default=None)
    ap.add_argument("--raw-image", default=None,
                    help="Raw page image path for VLM refine (optional, falls back to detection artifact source)")
    a = ap.parse_args()
    run(a.canon, a.out, work_id=a.work_id, state_dir=a.state_dir,
        raw_image_path=a.raw_image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
