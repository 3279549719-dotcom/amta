"""Benchmark B (路2) OCR 探测：对每页跑 detector+OCR 流水线，收集 3 引擎的识别文字。

路2 口径：detector 框出文字 → OCR 识别。与 GT 内容匹配算 CER/EM。
输出 output/ocr_result.json:
  { page_N: { "<ocr_engine>": [{bbox, ocr, confidence}], ... }, ... }
用法: python src/ocr_detect.py <src_dir> <page_count>
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from koharu_client import KoharuClient, KoharuError  # noqa: E402
from pipeline import OCR_ENGINES  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "output"
DETECTOR = "comic-text-detector"  # produce TextBoxes，作为 OCR 前置


def _bbox(block: dict) -> list[float]:
    t = block.get("transform", {})
    x = float(t.get("x", 0)); y = float(t.get("y", 0))
    w = float(t.get("w", t.get("width", 0))); h = float(t.get("h", t.get("height", 0)))
    return [round(x, 1), round(y, 1), round(x + w, 1), round(y + h, 1)]


def run_ocr(client: KoharuClient, page: Path, ocr_engine: str) -> list[dict]:
    proj = f"amta-ocr-{uuid.uuid4().hex[:8]}"
    client.close_current_project()
    client.create_project(proj)
    try:
        page_id = client.import_page(page)
        steps = [DETECTOR, ocr_engine]
        op = client.run_pipeline(page_ids=[page_id], steps=steps)
        result = client.wait_operation(op, timeout=1800)
        if result.get("status") == "failed":
            raise KoharuError(f"{ocr_engine} failed: {result}")
        # completed / completed_with_errors 都尝试读取（可能已有部分识别内容）
        nodes = client.get_page_nodes(page_id)
        blocks = KoharuClient.collect_blocks(nodes)
        out = []
        for b in blocks:
            ocr = (b.get("ocr") or "").strip()
            out.append({"bbox": _bbox(b), "ocr": ocr, "confidence": b.get("confidence")})
        return out
    finally:
        client.close_current_project()


def main(argv: list[str]) -> int:
    src = Path(argv[0])
    max_pages = int(argv[1]) if len(argv) > 1 else 10
    pages = sorted(src.glob("*.jpg"), key=lambda p: int(p.stem))[:max_pages]
    print(f"[ocr] {len(pages)} pages, ocr_engines={OCR_ENGINES}, detector={DETECTOR}", flush=True)
    client = KoharuClient()
    client.wait_server()
    out: dict[str, dict] = {}
    for idx, page in enumerate(pages):
        key = f"page_{idx}"
        out[key] = {"path": str(page), "engines": {}}
        for eng in OCR_ENGINES:
            print(f"[ocr] {key} / {eng} ...", flush=True)
            try:
                out[key]["engines"][eng] = run_ocr(client, page, eng)
            except Exception as e:  # noqa: BLE001
                print(f"[ocr] WARN {key} {eng}: {e}", flush=True)
                out[key]["engines"][eng] = []
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "ocr_result.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ocr] done -> {dest}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
