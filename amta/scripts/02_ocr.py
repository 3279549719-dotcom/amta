"""02_ocr 工位 — OCR:detection.json + raw 页 → artifacts/canon_text.json(per-work 契约,ADR-013)。

用法: python scripts/02_ocr.py --work-id <id> --det <detection.json> --raw <page图> --out <canon_text.json> [--page-idx N]
输出: canon_text.json = [{region_id, text, page}]  (region_id: page_<N>_u<MM>, 与 03 输入契约一致)
crop: artifacts/crops/<region_id>.png(供语义评审③按 region_id 读图)
断点: 输出文件已存在 → 跳过(00_run_all 调用方决定)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.ocr_engines import ocr_batch  # noqa: E402
from amta.paths import read_json, write_json  # noqa: E402
from PIL import Image  # noqa: E402


def _crop_by_region(raw: Path, blocks: list[dict], page_idx: int,
                    crop_dir: Path) -> list[tuple[str, dict, Path]]:
    """按 bbox 裁框,crop 文件名 = region_id.png(与语义评审③契约一致)。"""
    img = Image.open(raw)
    out = []
    crop_dir.mkdir(parents=True, exist_ok=True)
    i = 0
    for b in blocks:
        bb = b.get("bbox")
        if not bb or len(bb) != 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bb]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img.width, x2), min(img.height, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        rid = f"page_{page_idx}_u{i:02d}"
        i += 1
        crop = crop_dir / f"{rid}.png"
        img.crop((x1, y1, x2, y2)).save(crop)
        out.append((rid, b, crop))
    return out


def run(work_id: str, det_path: Path, raw_page: Path, out_path: Path,
        page_idx: int = 0, crop_dir: Path | None = None,
        engine: str = "auto") -> dict:
    det = read_json(det_path)
    blocks = det.get("blocks", [])
    crop_dir = crop_dir or out_path.parent / "crops"
    pairs = _crop_by_region(raw_page, blocks, page_idx, crop_dir)
    if not pairs:
        raise RuntimeError(f"02_ocr: no valid bbox in {det_path}")
    ocr_rows = ocr_batch([str(c) for _, _, c in pairs], engine=engine)
    ocr_by_crop = {r["crop"]: (r.get("ocr") or "").strip() for r in ocr_rows}
    canon = []
    for rid, b, crop in pairs:
        text = ocr_by_crop.get(str(crop), "")
        if not text:
            continue  # 空 OCR 跳过(防脏数据)
        canon.append({
            "region_id": rid,
            "text": text,
            "page": page_idx,
            "node_id": b.get("node_id"),
        })
    doc = {"work_id": work_id, "page": raw_page.stem, "regions": canon,
           "n_regions": len(canon), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    write_json(out_path, canon)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="02_ocr 工位")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--det", required=True, type=Path)
    ap.add_argument("--raw", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--page-idx", type=int, default=0, help="页面序号(region_id 用,0 基)")
    ap.add_argument("--engine", default="auto",
                    choices=["auto", "baberu", "local", "dashscope"],
                    help="OCR 引擎(auto=baberu fast path+回退; 默认 auto)")
    a = ap.parse_args()
    doc = run(a.work_id, a.det, a.raw, a.out, page_idx=a.page_idx, engine=a.engine)
    print(f"[02_ocr] {doc['page']}: {doc['n_regions']} regions -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
