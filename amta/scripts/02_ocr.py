"""02_ocr 工位 — OCR: detection.json + raw 页 → artifacts/{page}_canon.json（薄 CLI）。

最终选型：baberu-OCR（本地 ONNX）。VLM 校验已废弃。
实现: amta.ocr_station.ocr_page（裁框 → baberu 批量识别 → canon 落盘）。
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
        page_idx: int = 0, crop_dir: Path | None = None) -> dict:
    det = load_detection(det_path)
    doc = ocr_page(work_id, det, raw_page, out_path.parent, page_idx=page_idx,
                   ocr_fn=ocr_batch, crop_dir=crop_dir)
    write_json(out_path, doc)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="02_ocr 工位（baberu-OCR）")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--det", required=True, type=Path)
    ap.add_argument("--raw", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--page-idx", type=int, default=0, help="页面序号(0 基)")
    a = ap.parse_args()
    doc = run(a.work_id, a.det, a.raw, a.out, page_idx=a.page_idx)
    print(f"[02_ocr] {doc['page']}: {doc['n_regions']} regions -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
