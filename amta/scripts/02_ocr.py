"""02_ocr 工位 — OCR: detection.json + raw 页 → artifacts/{page}_canon.json（薄 CLI）。

Front3 Stage 2 双引擎会诊：Baberu 逐框 OCR + VLM contact sheet 批量校验，
输出 baberu_text + vlm_text + vlm_status；不自动除噪，假框由 Stage 3 裁决。
实现: amta.ocr_station.ocr_page（canon 落盘为 doc 信封，修 F2 双契约）。
断点: 输出文件已存在 → 跳过(00_run_all 调用方决定)。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.artifacts import load_detection  # noqa: E402
from amta.ocr_station import ocr_page  # noqa: E402
from amta.ocr_engines import ocr_batch  # noqa: E402,F401  # 供测试 monkeypatch 注入
from amta.paths import write_json  # noqa: E402


def run(work_id: str, det_path: Path, raw_page: Path, out_path: Path,
        page_idx: int = 0, engine: str = "auto", vlm_enabled: bool = True,
        crop_dir: Path | None = None) -> dict:
    det = load_detection(det_path)
    doc = ocr_page(work_id, det, raw_page, out_path.parent, page_idx=page_idx,
                   engine=engine, vlm_enabled=vlm_enabled, ocr_fn=ocr_batch,
                   crop_dir=crop_dir)
    write_json(out_path, doc)  # --out 与契约命名一致（00 传入），尊重显式 out
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="02_ocr 工位")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--det", required=True, type=Path)
    ap.add_argument("--raw", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--page-idx", type=int, default=0, help="页面序号(0 基)")
    ap.add_argument("--engine", default="auto",
                    choices=["auto", "baberu", "local", "dashscope"],
                    help="OCR 引擎(auto=baberu fast path+回退; 默认 auto)")
    ap.add_argument("--no-vlm", action="store_true", help="禁用 VLM 校验（只用 Baberu）")
    a = ap.parse_args()
    doc = run(a.work_id, a.det, a.raw, a.out, page_idx=a.page_idx,
              engine=a.engine, vlm_enabled=not a.no_vlm)
    print(f"[02_ocr] {doc['page']}: {doc['n_regions']} regions (vlm={doc['vlm_status']}) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
