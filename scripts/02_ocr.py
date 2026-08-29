"""02_ocr 工位 — OCR:detection.json + raw 页 → artifacts/canon.json(per-work 契约,ADR-013)。

Front3 Stage 2 双引擎会诊：
  - Baberu OCR：对每个框独立 OCR（现有逻辑）
  - VLM contact sheet 批量校验：所有 crop 拼图送 DeepSeek vision 转写
  - 输出双引擎文本并列：baberu_text + vlm_text + vlm_status
  - 不自动除噪：所有区域保留，假框由 Stage 3 LLM 判断

用法: python scripts/02_ocr.py --work-id <id> --det <detection.json> --raw <page图> --out <canon.json> [--page-idx N]
输出: canon.json = [{region_id, bbox, baberu_text, vlm_text, contained_in, source_engines, vlm_status}]
crop: artifacts/crops/<region_id>.png
断点: 输出文件已存在 → 跳过(00_run_all 调用方决定)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.ocr_engines import ocr_batch  # noqa: E402
from amta.paths import read_json, write_json  # noqa: E402
from amta.vlm_verify import vlm_verify_batch  # noqa: E402
from PIL import Image  # noqa: E402


def _get_vlm_api_key() -> str | None:
    """读 VLM API key：环境变量 VLM_API_KEY 优先，回退 CHAT_API_KEY，均无则 None。"""
    for key in ("VLM_API_KEY", "CHAT_API_KEY"):
        v = os.environ.get(key)
        if v:
            return v
    # 回退 .env
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            for key in ("VLM_API_KEY", "CHAT_API_KEY"):
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _crop_by_region(
    raw: Path, blocks: list[dict], page_idx: int, crop_dir: Path
) -> list[tuple[str, dict, Path, Image.Image]]:
    """按 bbox 裁框，crop 文件名 = region_id.png。

    Returns:
        [(region_id, block, crop_path, pil_image), ...]
    """
    img = Image.open(raw)
    out = []
    crop_dir.mkdir(parents=True, exist_ok=True)
    for i, b in enumerate(blocks):
        bb = b.get("bbox")
        if not bb or len(bb) != 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bb]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img.width, x2), min(img.height, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        rid = f"page_{page_idx}_u{i:02d}"
        crop = crop_dir / f"{rid}.png"
        pil_crop = img.crop((x1, y1, x2, y2))
        pil_crop.save(crop)
        out.append((rid, b, crop, pil_crop))
    return out


def run(
    work_id: str,
    det_path: Path,
    raw_page: Path,
    out_path: Path,
    page_idx: int = 0,
    crop_dir: Path | None = None,
    engine: str = "auto",
    vlm_enabled: bool = True,
) -> dict:
    det = read_json(det_path)
    blocks = det.get("blocks", [])
    crop_dir = crop_dir or out_path.parent / "crops"
    pairs = _crop_by_region(raw_page, blocks, page_idx, crop_dir)
    if not pairs:
        raise RuntimeError(f"02_ocr: no valid bbox in {det_path}")

    # Baberu OCR（现有逻辑）
    t_baberu_start = time.time()
    ocr_rows = ocr_batch([str(c) for _, _, c, _ in pairs], engine=engine)
    ocr_by_crop = {r["crop"]: (r.get("ocr") or "").strip() for r in ocr_rows}
    baberu_elapsed = time.time() - t_baberu_start

    # VLM contact sheet 批量校验（Front3 Stage 2 新增）
    vlm_result = {"texts": None, "status": "skipped", "raw_output": "", "elapsed": 0, "retries": 0}
    if vlm_enabled:
        api_key = _get_vlm_api_key()
        if api_key:
            t_vlm_start = time.time()
            crop_images = [pil for _, _, _, pil in pairs]
            try:
                vlm_result = vlm_verify_batch(crop_images, api_key=api_key)
            except Exception as e:
                vlm_result = {
                    "texts": None,
                    "status": "failed",
                    "raw_output": str(e),
                    "elapsed": time.time() - t_vlm_start,
                    "retries": 0,
                }
        else:
            vlm_result["status"] = "skipped"
            vlm_result["raw_output"] = "No VLM_API_KEY or CHAT_API_KEY configured"

    # 合并双引擎输出（不跳过空 OCR，所有区域保留）
    canon = []
    vlm_texts = vlm_result.get("texts")
    for i, (rid, b, crop, _pil) in enumerate(pairs):
        baberu_text = ocr_by_crop.get(str(crop), "")
        vlm_text = vlm_texts[i] if (vlm_texts and i < len(vlm_texts)) else None
        item = {
            "region_id": rid,
            "bbox": b.get("bbox"),
            "baberu_text": baberu_text,
            "vlm_text": vlm_text,
            "contained_in": b.get("contained_in"),
            "source_engines": b.get("source_engines", []),
            "vlm_status": vlm_result["status"],
            "page": page_idx,
        }
        # 透传可选字段
        for k in ("category", "bubble_type", "node_id"):
            if b.get(k) is not None:
                item[k] = b[k]
        canon.append(item)

    # Tracing: Stage 2 处理过程
    trace = {
        "page": raw_page.stem,
        "n_blocks": len(pairs),
        "baberu_elapsed": round(baberu_elapsed, 2),
        "vlm_status": vlm_result["status"],
        "vlm_elapsed": round(vlm_result.get("elapsed", 0), 2),
        "vlm_retries": vlm_result.get("retries", 0),
        "vlm_raw_output": vlm_result.get("raw_output", ""),
        "baberu_vs_vlm_diff": [
            {
                "region_id": c["region_id"],
                "baberu": c["baberu_text"],
                "vlm": c["vlm_text"],
                "match": c["baberu_text"] == (c["vlm_text"] or ""),
            }
            for c in canon
            if c["vlm_text"] is not None
        ],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    trace_path = out_path.parent / f"{raw_page.stem}_02_ocr_trace.json"
    write_json(trace_path, trace)

    doc = {
        "work_id": work_id,
        "page": raw_page.stem,
        "items": canon,
        "n_regions": len(canon),
        "vlm_status": vlm_result["status"],
        "front3_version": "2.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(out_path, canon)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="02_ocr 工位")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--det", required=True, type=Path)
    ap.add_argument("--raw", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--page-idx", type=int, default=0, help="页面序号(0 基)")
    ap.add_argument(
        "--engine",
        default="auto",
        choices=["auto", "baberu", "local", "dashscope"],
        help="OCR 引擎(auto=baberu fast path+回退; 默认 auto)",
    )
    ap.add_argument("--no-vlm", action="store_true", help="禁用 VLM 校验（只用 Baberu）")
    a = ap.parse_args()
    doc = run(
        a.work_id,
        a.det,
        a.raw,
        a.out,
        page_idx=a.page_idx,
        engine=a.engine,
        vlm_enabled=not a.no_vlm,
    )
    print(f"[02_ocr] {doc['page']}: {doc['n_regions']} regions (vlm={doc['vlm_status']}) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
