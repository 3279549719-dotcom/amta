"""02_ocr 工位 — OCR: detection.json + raw 页 → artifacts/{page}_canon.json（薄 CLI）。

引擎可插拔: hayai(默认,HayaiOCR-v2.1) / baberu(ONNX内置免费) / manga_ocr(kha-white)。
默认关闭硬规则过滤（--rule-filter 开启），VLM 校验默认关闭（--vlm 开启）。
实现: amta.ocr_station.ocr_page（深模块，含双引擎兜底）。
断点: 输出文件已存在 → 跳过(00_run_all 调用方决定)。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.artifacts import load_detection  # noqa: E402
from amta.ocr_station import ocr_page  # noqa: E402
from amta.ocr_engines import ocr_batch  # noqa: E402
from amta.paths import write_json  # noqa: E402


def run(work_id: str, det_path: Path, raw_page: Path, out_path: Path,
        page_idx: int = 0, engine: str = "hayai", vlm_enabled: bool = False,
        rule_filter_enabled: bool = False,
        crop_dir: Path | None = None, fallback_ocr_fn=None) -> dict:
    det = load_detection(det_path)

    doc = ocr_page(work_id, det, raw_page, out_path.parent, page_idx=page_idx,
                   engine=engine, vlm_enabled=vlm_enabled,
                   rule_filter_enabled=rule_filter_enabled,
                   ocr_fn=ocr_batch, crop_dir=crop_dir,
                   fallback_ocr_fn=fallback_ocr_fn)
    write_json(out_path, doc)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="02_ocr 工位（引擎可插拔: baberu/hayai/manga_ocr）")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--det", required=True, type=Path)
    ap.add_argument("--raw", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--page-idx", type=int, default=0, help="页面序号(0 基)")
    ap.add_argument("--engine", default="hayai", choices=["baberu", "hayai", "manga_ocr"],
                    help="OCR 引擎（默认 hayai，HayaiOCR-v2.1）")
    ap.add_argument("--rule-filter", action="store_true",
                    help="启用硬规则过滤（默认关闭，过滤纯标点/纯数字/边缘框/极端长宽比）")
    ap.add_argument("--vlm", action="store_true", help="启用 VLM 校验（默认关闭）")
    a = ap.parse_args()
    doc = run(a.work_id, a.det, a.raw, a.out, page_idx=a.page_idx,
              engine=a.engine, vlm_enabled=a.vlm,
              rule_filter_enabled=a.rule_filter)
    print(f"[02_ocr] {doc['page']}: {doc['n_regions']} regions "
          f"(engine={a.engine}, rule_filter={a.rule_filter}, vlm={doc['vlm_status']}) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
