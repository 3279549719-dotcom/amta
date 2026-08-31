"""03_translate 工位 — 读 canon → DeepSeek 翻译 → translation.json（薄 CLI）。

用法: python scripts/03_translate.py --canon <canon.json> --out <translation.json>
      [--work-id ID] [--state-dir DIR] [--trace] [--with-plan] [--with-vision-plan] [--crop-dir DIR]
实现: amta.translate_station.translate_page（护栏/失败记录/suggestions 全在实现内）。
run() 保留作兼容入口（test_translate / eval_stage3 仍 import run）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.artifacts import load_canon  # noqa: E402
from amta.paths import write_json  # noqa: E402
from amta.translate_station import translate_page  # noqa: E402


def run(canon_path: str | Path, out_path: str | Path, *,
        work_id: str | None = None, state_dir: str | Path | None = None,
        trace_path: str | Path | None = None, with_plan: bool = False,
        with_vision_plan: bool = False, crop_dir: str | Path | None = None,
        mode: str = "minimal", raw_image_path: str | Path | None = None) -> dict:
    """读 canon → 翻译 → 落盘 translation.json（兼容旧 run 签名）。"""
    try:
        canon = load_canon(canon_path)  # normalize + validate（旧裸 list 兼容）
    except ValueError as e:
        raise ValueError(f"canon input schema failed: {e}") from e
    out = translate_page(work_id, canon,
                         state_dir=state_dir, page=canon.get("page") or None,
                         with_plan=with_plan, with_vision_plan=with_vision_plan,
                         trace_enabled=bool(trace_path), crop_dir=crop_dir,
                         mode=mode, raw_image_path=raw_image_path)
    trace, out2 = out.pop("_trace", None), out
    write_json(out_path, out2)
    if trace_path and trace:
        write_json(Path(trace_path), {"work_id": work_id or "", "trace": trace})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canon", required=True, help="canon.json 路径（doc 或旧裸 list）")
    ap.add_argument("--out", required=True, help="输出 translation.json 路径")
    ap.add_argument("--work-id", default=None)
    ap.add_argument("--state-dir", default=None)
    ap.add_argument("--trace", default=None, help="LLM/工具调用观测落盘路径(可选)")
    ap.add_argument("--with-plan", action="store_true",
                    help="翻译前 LLM 扫描全页，标记 invalid/duplicate 框")
    ap.add_argument("--with-vision-plan", action="store_true",
                    help="VLM 规划阶段（带整页图）")
    ap.add_argument("--crop-dir", default=None, help="lookup_image 工具所需 crop 目录")
    ap.add_argument("--mode", choices=["minimal", "legacy"], default="minimal",
                    help="minimal: 2 LLM calls/page, zero tools (default); legacy: old tool-loop path")
    ap.add_argument("--raw-image", default=None,
                    help="Raw page image path for VLM refine (minimal mode only; optional, falls back to detection artifact source)")
    a = ap.parse_args()
    run(a.canon, a.out, work_id=a.work_id, state_dir=a.state_dir, trace_path=a.trace,
        with_plan=a.with_plan, with_vision_plan=a.with_vision_plan, crop_dir=a.crop_dir,
        mode=a.mode, raw_image_path=a.raw_image)
    print(f"[03_translate] -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
