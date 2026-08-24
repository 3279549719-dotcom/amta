"""在 recall_gt 的 GT 框上跑指定 OCR 引擎（local llama-server / dashscope qwen-vl-ocr）。

实现收敛在 amta.ocr_engines（引擎请求）与 amta.gt_alignment（GT→detector 框对齐裁剪），
本文件只保留 CLI 编排与落盘。
用法: python scripts/ocr_run.py --engine local|dashscope [--pages N] [--out ...] [--write-meta ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.gt_alignment import crop_regions  # noqa: E402
from amta.ocr_engines import (  # noqa: E402
    DASHSCOPE_URL,
    dashscope_ocr_batch,
    local_ocr_batch,
    send_one,
)
from amta.paths import DATA, ensure_utf8_stdio, write_json  # noqa: E402

ensure_utf8_stdio()

__all__ = ["crop_regions", "send_one", "local_ocr_batch", "dashscope_ocr_batch", "DASHSCOPE_URL"]


def _load_det_boxes(det_path: Path) -> dict[int, list[dict]]:
    """读 ocr_result.json → {GT 页号: [{bbox, text}]}。

    注意页码偏移：ocr_result 的 page_N 是 0 基（page_0=1.jpg），recall_gt 是 1 基（page_1=1.jpg），
    故 det 的 page_N 要存成 GT 页号 N+1。
    """
    det_boxes: dict[int, list[dict]] = {}
    if not det_path.exists():
        return det_boxes
    det = json.loads(det_path.read_text(encoding="utf-8"))
    for pkey, pinfo in det.items():
        pnum0 = int(pkey.split("_")[1])
        eng = (pinfo.get("engines") or {}).get("manga-ocr", [])
        det_boxes[pnum0 + 1] = [{"bbox": b.get("bbox"), "text": b.get("ocr") or ""} for b in eng]
    return det_boxes


def main() -> int:
    ap = argparse.ArgumentParser(description="在 recall_gt 的 GT 框上跑指定 OCR 引擎")
    ap.add_argument("--engine", choices=["local", "dashscope"], required=True)
    ap.add_argument("--pages", type=int, default=None, help="只处理前 N 页（默认全部）")
    ap.add_argument("--out", default=None, help="preds JSON 输出路径")
    ap.add_argument("--src-dir", default=r"D:\我的汉化\汉化作品\东方\单翼停留之地")
    ap.add_argument("--gt", default=str(DATA / "recall_gt.json"))
    ap.add_argument("--det", default=str(DATA / "ocr_result.json"),
                    help="detector 输出（含全尺寸 bbox），评测坐标源；缺省 ocr_result.json")
    ap.add_argument("--crop-dir", default=str(DATA / "ocr_crops"))
    ap.add_argument("--model", default=None)
    ap.add_argument("--write-meta", default=None,
                    help="把 crop→GT 对齐 meta（含 content/type/bbox）落盘到该路径，供评测复用")
    a = ap.parse_args()

    gt = json.loads(Path(a.gt).read_text(encoding="utf-8"))
    if a.pages:
        keys = sorted(gt["pages"].keys(), key=lambda k: int(k.split("_")[1]))[: a.pages]
        gt = {"pages": {k: gt["pages"][k] for k in keys}}

    page_paths = {int(k.split("_")[1]): str(Path(a.src_dir) / f"{int(k.split('_')[1])}.jpg")
                  for k in gt["pages"]}
    det_boxes = _load_det_boxes(Path(a.det))
    crops, meta = crop_regions(gt, page_paths, a.crop_dir, det_boxes=det_boxes)
    print(f"[ocr_run] {len(crops)} crops -> {a.crop_dir}", file=sys.stderr)
    if a.write_meta:
        write_json(a.write_meta, meta)
        print(f"[ocr_run] meta -> {a.write_meta}", file=sys.stderr)

    if a.engine == "local":
        preds = local_ocr_batch(crops, model=a.model or "paddle")
    else:
        preds = dashscope_ocr_batch(crops, model=a.model or "qwen-vl-ocr-latest")

    for p in preds:
        print(f"{Path(p['crop']).name}: {p['ocr']}")
    if a.out:
        write_json(a.out, preds)
        print(f"[ocr_run] preds -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
